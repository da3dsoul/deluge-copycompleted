# -*- coding: utf-8 -*-
#
# Copyright (C) 2010 Sam Lai <sam@edgylogic.com>
# Copyright (C) 2009 Andrew Resch <andrewresch@gmail.com>
#
# Basic plugin template created by:
# Copyright (C) 2008 Martijn Voncken <mvoncken@gmail.com>
# Copyright (C) 2007-2009 Andrew Resch <andrewresch@gmail.com>
#
# Deluge is free software.
#
# You may redistribute it and/or modify it under the terms of the
# GNU General Public License, as published by the Free Software
# Foundation; either version 3 of the License, or (at your option)
# any later version.
#
# deluge is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with deluge.    If not, write to:
#     The Free Software Foundation, Inc.,
#     51 Franklin Street, Fifth Floor
#     Boston, MA  02110-1301, USA.
#
#    In addition, as a special exception, the copyright holders give
#    permission to link the code of portions of this program with the OpenSSL
#    library.
#    You must obey the GNU General Public License in all respects for all of
#    the code used other than OpenSSL. If you modify file(s) with this
#    exception, you may extend this exception to your version of the file(s),
#    but you are not obligated to do so. If you do not wish to do so, delete
#    this exception statement from your version. If you delete this exception
#    statement from all source files in the program, then also delete it here.
#

from __future__ import unicode_literals

import os
import shutil
import threading
import logging

from deluge.plugins.pluginbase import CorePluginBase
import deluge.component as component
import deluge.configmanager
from deluge.core.rpcserver import export
from deluge.event import DelugeEvent
from deluge.ui.client import client

from twisted.internet import reactor

log = logging.getLogger(__name__)

DEFAULT_PREFS = {
    "copy_to" : "",
    "umask" : "",
    "move_to": False,
    "append_label_todir": False
}

class TorrentCopiedEvent(DelugeEvent):
    """
    Emitted when a torrent is copied.
    """
    def __init__(self, torrent_id, old_path, new_path, path_pairs):
        """
        :param torrent_id - hash representing torrent in Deluge
        :param old_path - original path for the torrent
        :param new_path - new path for the torrent
        :param path_pairs - a list of tuples, ( old path, new path )
        """
        self._args = [ torrent_id, old_path, new_path, path_pairs ]

class Core(CorePluginBase):
    def enable(self):
        self.config = deluge.configmanager.ConfigManager("copycompleted.conf", DEFAULT_PREFS)

        # validate settings here as an aid to user
        # don't act differently, as this won't be called again if settings are
        # changed during the session.
        if self.config["copy_to"].strip() == "" or not os.path.isdir(self.config["copy_to"]):
            log.error("COPYCOMPLETED: No path to copy to was specified, or that path was invalid. Please amend.")

        # Get notified when a torrent finishes downloading
        component.get("EventManager").register_event_handler("TorrentFinishedEvent", self.on_torrent_finished)

    def disable(self):
        try:
            self.timer.cancel()
        except:
            pass
        component.get("EventManager").deregister_event_handler("TorrentFinishedEvent", self.on_torrent_finished)

    def update(self):
        pass

    def on_torrent_finished(self, torrent_id):
        """
        Copy the torrent now. It will do this in a separate thread to avoid
        freezing up this thread (which causes freezes in the daemon and hence
        web/gtk UI.)
        """
        torrent = component.get("TorrentManager").torrents[torrent_id]
        info = torrent.get_status([ "name", "save_path", "move_on_completed", "move_on_completed_path" ])
        label = get_label["label"]
        old_path = info["move_on_completed_path"] if info["move_on_completed"] else info["save_path"]
        new_path = self.config["copy_to"]  + "/" + label if self.config["append_label_todir"] else self.config["copy_to"]
        if not os.path.exists(new_path):
            os.makedirs(new_path)
        files = torrent.get_files()
        umask = self.config["umask"]
        
        # validate parameters
        if new_path.strip() == "" or not os.path.isdir(new_path):
            log.error("COPYCOMPLETED: No path to copy to was specified, or that path was invalid. Copy aborted.")
            return
        
        log.info("COPYCOMPLETED: Copying %s from %s to %s" % (info["name"], old_path, new_path)) 
        copy_thread = threading.Thread(target=Core._thread_copy, args=(torrent_id, old_path, new_path, files, umask))
        copy_thread.setDaemon(True)
        copy_thread.start()
    def on_torrent_copied(self, torrent_id, old_path, new_path, path_pairs):
        """
        Remove old path if option enabled
        """
        log.debug("COPYCOMPLETED: Torrent Copied Event: %s, %s, %s, %s", torrent_id, old_path, new_path, path_pairs)
        if self.config["move_to"] and path_pairs:
            log.debug("COPYCOMPLETED: Attempting Move To Path")
            torrent = component.get("TorrentManager").torrents[torrent_id]
            files = torrent.get_files()
            torrent.pause()
            old_fp_dirs=[]
            for old_fp,new_fp in path_pairs:
                try:
                    if os.path.exists(new_fp):
                        log.debug("COPYCOMPLETED: Removing files: %s", old_fp)
                        os.remove(old_fp)
                        old_fp_dirs.append(os.path.dirname(old_fp))
                    else:
                        log.error("COPYCOMPLETED: %s missing new location files. Skipping.", new_fp)
                        break
                except Exception as e:
                    log.error("COPYCOMPLETED: Could not remove file.\n%s", e)
                    break
            else:
                # Clean up empty dirs
                old_fp_dirs = sorted(list(set(old_fp_dirs)), key=len, reverse=True)
                log.debug("COPYCOMPLETED: Cleanup empty dirs: %s", old_fp_dirs)
                try:
                    for old_fp_dir in old_fp_dirs:
                        if os.path.isdir(old_fp_dir):
                                os.removedirs(old_fp_dir)
                except OSError as e:
                    log.error("COPYCOMPLETED: Error with removing dirs: %s", e)
                else:
                    if not torrent.move_storage(new_path):
                        log.error("COPYCOMPLETED: Move Storage failed")

            torrent.resume()
        
    def on_alert_performance(self, alert):
        log.debug("COPYCOMPLETED: Performance Alert: %s", alert.message())
        if 'send buffer watermark too low' in alert.message():
            try:
                settings = self.session.settings()
                send_buffer_watermark = settings.send_buffer_watermark
                log.debug("COPYCOMPLETED: send_buffer_watermark currently set to: %s bytes", send_buffer_watermark)
                # Cap the buffer at 5MiB, based upon lt high_performance settings
                buffer_cap = 5 * 1024 * 1024
                # if send buffer is too small, try doubling its size
                if send_buffer_watermark <= buffer_cap:
                    log.debug("COPYCOMPLETED: Setting send_buffer_watermark to: %s bytes", 2 * send_buffer_watermark)
                    setattr(settings, "send_buffer_watermark", 2 * send_buffer_watermark)
                    self.session.set_settings(settings)
                else:
                    log.debug("COPYCOMPLETED: send_buffer_watermark has hit buffer cap: %s bytes", buffer_cap)
            except:
                return

    @staticmethod
    def _thread_copy(torrent_id, old_path, new_path, files, umask):
        # apply different umask if available
        if umask:
            log.debug("COPYCOMPLETED: Applying new umask of octal %s" % umask)
            new_umask = int(umask, 8)
            new_umask = '0o' + new_umask[1:4]
            old_umask = os.umask(new_umask)
        
        path_pairs = [ ]
        for f in files:
            try:
                old_file_path = os.path.join(old_path, f["path"])
                new_file_path = os.path.join(new_path, f["path"])

                # check that this file exists at the current location
                if not os.path.exists(old_file_path):
                    log.debug("COPYCOMPLETED: %s was not downloaded. Skipping." % f["path"])
                    break

                # check that this file doesn't already exist at the new location
                if os.path.exists(new_file_path):
                    log.info("COPYCOMPLETED: %s already exists in the destination. Skipping." % f["path"])
                    break

                log.info("COPYCOMPLETED: Copying %s to %s" % (old_file_path, new_file_path))

                # ensure dirs up to this exist
                if not os.path.exists(os.path.dirname(new_file_path)):
                    os.makedirs(os.path.dirname(new_file_path))

                # copy the file
                shutil.copy2(old_file_path, new_file_path)

                # amend file mode with umask if specified
                if umask:
                    # choose 0666 so execute bit is not set for files
                    os.chmod(new_file_path, (~new_umask & 0o666))

                path_pairs.append(( old_file_path, new_file_path ))

            except Exception as e:
                os.error("COPYCOMPLETED: Could not copy file.\n%s" % str(e))

        # revert new umask
        if umask:
            log.debug("COPYCOMPLETED: reverting umask to original")
            os.umask(old_umask)

        component.get("EventManager").emit(TorrentCopiedEvent(torrent_id, old_path, new_path, path_pairs))
            
    @export()
    def set_config(self, config):
        "sets the config dictionary"
        for key in config.keys():
            self.config[key] = config[key]
        self.config.save()

    @export()
    def get_config(self):
        "returns the config dictionary"
        return self.config.config
