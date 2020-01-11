# -*- coding: utf-8 -*-
#
# Copyright (C) 2009 GazpachoKing <chase.sterling@gmail.com>
#
# Basic plugin template created by:
# Copyright (C) 2008 Martijn Voncken <mvoncken@gmail.com>
# Copyright (C) 2007-2009 Andrew Resch <andrewresch@gmail.com>
# Copyright (C) 2009 Damien Churchill <damoxc@gmail.com>
#
# This file is part of Deluge and is licensed under GNU General Public License 3.0, or later, with
# the additional special exception to link portions of this program with the OpenSSL library.
# See LICENSE for more details.
#

from __future__ import unicode_literals

import logging
import os

import gi  # isort:skip (Required before Gtk import).

gi.require_version('Gtk', '3.0')  # NOQA: E402

# isort:imports-thirdparty
from gi.repository import Gtk

# isort:imports-firstparty
import deluge.common
import deluge.component as component
from deluge.plugins.pluginbase import Gtk3PluginBase
from deluge.ui.client import client
from deluge.ui.gtk3 import dialogs

# isort:imports-localfolder
from .common import get_resource

log = logging.getLogger(__name__)

class GtkUI(Gtk3PluginBase):
    def enable(self):
        self.glade = gtk.glade.XML(get_resource("copycompleted_prefs.glade"))
        component.get("Preferences").add_page("Copy Completed", self.glade.get_widget("copycompleted_prefs_box"))
        component.get("PluginManager").register_hook("on_apply_prefs", self.on_apply_prefs)
        component.get("PluginManager").register_hook("on_show_prefs", self.on_show_prefs)
        self.on_show_prefs()

    def disable(self):
        component.get("Preferences").remove_page("Copy Completed")
        component.get("PluginManager").deregister_hook("on_apply_prefs", self.on_apply_prefs)
        component.get("PluginManager").deregister_hook("on_show_prefs", self.on_show_prefs)
        del self.glade

   def on_apply_prefs(self):
        log.debug("Applying prefs for Copy Completed")
        if client.is_localhost():
            path = self.glade.get_widget("folderchooser_path").get_current_folder()
        else:
            path = self.glade.get_widget("entry_path").get_text()

        umask = ''.join(map(str, [
            0,'o',
            self.glade.get_widget("spinbutton_umask1").get_value_as_int(),
            self.glade.get_widget("spinbutton_umask2").get_value_as_int(),
            self.glade.get_widget("spinbutton_umask3").get_value_as_int()
            ]))

        config = {
            "copy_to": path,
            "umask": umask,
            "move_to": self.glade.get_widget("radiobutton_move_to").get_active(),
            "append_label_todir": self.glade.get_widget("append_label_todir").get_active()
        }

        client.copycompleted.set_config(config)

    def on_show_prefs(self):
        if client.is_localhost():
            self.glade.get_widget("folderchooser_path").show()
            self.glade.get_widget("entry_path").hide()
        else:
            self.glade.get_widget("folderchooser_path").hide()
            self.glade.get_widget("entry_path").show()

        def on_get_config(config):
            if client.is_localhost():
                self.glade.get_widget("folderchooser_path").set_current_folder(config["copy_to"])
            else:
                self.glade.get_widget("entry_path").set_text(config["copy_to"])


            umask = map(int, str(config["umask"]))
            self.glade.get_widget("spinbutton_umask1").set_value(umask[1])
            self.glade.get_widget("spinbutton_umask2").set_value(umask[2])
            self.glade.get_widget("spinbutton_umask3").set_value(umask[3])
            self.glade.get_widget("radiobutton_move_to").set_active(config["move_to"])
            self.glade.get_widget("append_label_todir").set_active(config["append_label_todir"])

        client.copycompleted.get_config().addCallback(on_get_config)
