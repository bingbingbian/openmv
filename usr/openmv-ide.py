#!/usr/bin/env python
import sys, os, os.path
import gtk
import gtksourceview2 as gtksourceview
import gio
import pango
import gobject
import vte
import serial
from time import sleep
import usb.core
import usb.util
import numpy as np
import openmv
from os.path import expanduser
ui_path =os.path.dirname(os.path.realpath(__file__))+"/openmv-ide.glade"
config_path = expanduser("~")+"/.openmvide.config"

SCALE =1

class OMVGtk:
    def __init__(self):
        #Set the Glade file
        self.builder = gtk.Builder()
        self.builder.add_from_file(ui_path)

        # get top window
        self.window = self.builder.get_object("top_window")

        # status bar stuff
        self.statusbar = self.builder.get_object("statusbar")
        self.statusbar_ctx = self.statusbar.get_context_id("default")

        #save toolbutton
        self.save_button = self.builder.get_object('save_file_toolbutton')
        self.save_button.set_sensitive(False)

        #configure gtksourceview
        sourceview = self.builder.get_object('gtksourceview')
        self.buffer = gtksourceview.Buffer()
        mgr = gtksourceview.style_scheme_manager_get_default()
        style_scheme = mgr.get_scheme('classic')
        if style_scheme:
            self.buffer.set_style_scheme(style_scheme)
        lang_manager = gtksourceview.language_manager_get_default()
        self.buffer.set_highlight_syntax(True)
        self.buffer.set_language(lang_manager.get_language("python"))
        self.buffer.connect("changed", self.text_changed)

        #configure the terminal
        self.fd = -1
        self.terminal = self.builder.get_object('terminal')
        self.terminal.set_size(80,24)

        # open last opened file
        if os.path.isfile(config_path):
            with open(config_path, "r") as file:
                self.file_path = file.read()
            if os.path.isfile(self.file_path):
                with open(self.file_path, "r") as file:
                    self.buffer.set_text(file.read())
                    self.window.set_title(os.path.basename(self.file_path))
            else:
                self.file_path = None

        sourceview.set_buffer(self.buffer)

        # get drawingarea
        self.pixbuf = None
        self.drawingarea = self.builder.get_object("drawingarea")
        self.da_menu = self.builder.get_object("da_menu")

        # selection coords
        self.x1 =0
        self.y1 =0
        self.x2 =0
        self.y2 =0
        self.selection_started=False
        self.sel_ended=False

        # set control scales attributes
        self.builder.get_object("contrast_adjust").attr=    openmv.ATTR_CONTRAST
        self.builder.get_object("brightness_adjust").attr=  openmv.ATTR_BRIGHTNESS
        self.builder.get_object("saturation_adjust").attr=  openmv.ATTR_SATURATION
        self.builder.get_object("gainceiling_adjust").attr= openmv.ATTR_GAINCEILING

        #connect signals
        signals = {
            "on_top_window_destroy"         : self.quit,
            "on_connect_clicked"            : self.connect_clicked,
            "on_execute_clicked"            : self.execute_clicked,
            "on_stop_clicked"               : self.stop_clicked,
            "on_motion_notify"              : self.motion_notify,
            "on_button_press"               : self.button_pressed,
            "on_button_release"             : self.button_released,
            "on_open_file"                  : self.open_file,
            "on_save_file"                  : self.save_file,
            "on_save_file_as"               : self.save_file_as,
            "on_save_template_activate"     : self.save_template,
            "on_save_descriptor_activate"   : self.save_descriptor,
            "on_ctrl_scale_value_changed"   : self.on_ctrl_scale_value_changed,
            "on_zoomin_clicked"             : self.zoomin_clicked,
            "on_zoomout_clicked"            : self.zoomout_clicked,
            "on_bestfit_clicked"            : self.bestfit_clicked,
            "on_updatefb_clicked"           : self.updatefb_clicked,
        }
        self.builder.connect_signals(signals)

        self.connected = False
        self.builder.get_object('connect_button').set_sensitive(True)
        self.builder.get_object('exec_button').set_sensitive(False)
        self.builder.get_object('stop_button').set_sensitive(False)
        self.builder.get_object('zoomin_button').set_sensitive(False)
        self.builder.get_object('zoomout_button').set_sensitive(False)
        self.builder.get_object('bestfit_button').set_sensitive(False)
        self.builder.get_object('refresh_button').set_sensitive(False)


    def show_message_dialog(self, msg_type, msg):
        message = gtk.MessageDialog(parent=self.window, flags=gtk.DIALOG_DESTROY_WITH_PARENT,
                                    type=msg_type, buttons=gtk.BUTTONS_OK, message_format=msg)
        message.run()
        message.destroy()

    def connect(self):
        self.terminal = self.builder.get_object('terminal')
        try:
            # open VCP and configure the terminal
            self.fd = os.open("/dev/ttyACM0", os.O_RDWR)
            self.terminal.reset(True, True)
            self.terminal.set_size(80,24)
            self.terminal.set_pty(self.fd)
        except Exception, e:
            self.show_message_dialog(gtk.MESSAGE_ERROR, "Faild to connect to OpenMV\n%s"%e)
            return

        try:
            # init openmv
            openmv.init()

            # interrupt any running code
            openmv.stop_script()
            sleep(0.1)
        except Exception, e:
            self.show_message_dialog(gtk.MESSAGE_ERROR, "Faild to connect to OpenMV\n%s"%e)
            return

        self.connected = True
        self.builder.get_object('connect_button').set_sensitive(False)
        self.builder.get_object('exec_button').set_sensitive(True)
        self.builder.get_object('stop_button').set_sensitive(True)
        self.builder.get_object('zoomin_button').set_sensitive(True)
        self.builder.get_object('zoomout_button').set_sensitive(True)
        self.builder.get_object('bestfit_button').set_sensitive(True)
        self.builder.get_object('refresh_button').set_sensitive(True)

    def disconnect(self):
        try:
            # close VCP
            os.close(self.fd)
        except OSError:
            pass

        #reset terminal
        self.terminal.set_pty(-1)
        self.terminal.reset(True, True)

        try:
            # stop running code
            openmv.stop_script();
        except:
            pass

        # release OpenMV
        openmv.release()

        self.connected = False
        self.builder.get_object('connect_button').set_sensitive(True)
        self.builder.get_object('exec_button').set_sensitive(False)
        self.builder.get_object('stop_button').set_sensitive(False)
        self.builder.get_object('zoomin_button').set_sensitive(False)
        self.builder.get_object('zoomout_button').set_sensitive(False)
        self.builder.get_object('bestfit_button').set_sensitive(False)
        self.builder.get_object('refresh_button').set_sensitive(False)


    def connect_clicked(self, widget):
        self.connect()

    def execute_clicked(self, widget):
        buf = self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter())
        # interrupt any running code
        openmv.stop_script()
        sleep(0.1)
        # exec script
        openmv.exec_script(buf)

    def stop_clicked(self, widget):
        openmv.stop_script();

    def zoomin_clicked(self, widget):
        global SCALE
        SCALE+=1

    def zoomout_clicked(self, widget):
        global SCALE
        if SCALE>1:
            SCALE-=1

    def bestfit_clicked(self, widget):
        global SCALE
        SCALE=1

    def updatefb_clicked(self, widget):
        openmv.fb_update()

    def button_pressed(self, widget, event):
        self.x1 = int(event.x)
        self.y1 = int(event.y)
        self.x2 = int(event.x)
        self.y2 = int(event.y)
        self.selection_started = True

    def button_released(self, widget, event):
        self.x2 = int(event.x)
        self.y2 = int(event.y)
        self.selection_started = False
        self.da_menu.popup(None, None, None, event.button, event.time, None)
        self.da_menu.show_all()

    def motion_notify(self, widget, event):
        x = int(event.x)
        y = int(event.y)
        self.x2 = int(event.x)
        self.y2 = int(event.y)
        if self.pixbuf and x < self.pixbuf.get_width() and y < self.pixbuf.get_height():
            pixel = self.pixbuf.get_pixels_array()[y][x]
            rgb = "(%d, %d, %d)" %(pixel[0], pixel[1], pixel[2])
            self.statusbar.pop(self.statusbar_ctx)
            self.statusbar.push(self.statusbar_ctx, rgb)

    def update_drawing(self):
        if (not self.connected):
            return True

        try:
            # read drawingarea
            fb = openmv.fb_dump()
            if fb:
                # convert to RGB888 and blit
                self.pixbuf = gtk.gdk.pixbuf_new_from_array(fb[2].reshape((fb[1], fb[0], 3)), gtk.gdk.COLORSPACE_RGB, 8)
                self.pixbuf = self.pixbuf.scale_simple(fb[0]*SCALE, fb[1]*SCALE, gtk.gdk.INTERP_BILINEAR)

                self.drawingarea.realize();
                cm = self.drawingarea.window.get_colormap()
                gc = self.drawingarea.window.new_gc(foreground=cm.alloc_color('#FFFFFF',True,False))

                self.drawingarea.set_size_request(fb[0]*SCALE, fb[1]*SCALE)
                self.drawingarea.window.draw_pixbuf(gc, self.pixbuf, 0, 0, 0, 0)
                if self.selection_started or self.da_menu.flags() & gtk.MAPPED:
                    self.drawingarea.window.draw_rectangle(gc, False, self.x1, self.y1, self.x2-self.x1, self.y2-self.y1)
        except Exception, e:
            self.disconnect()
            self.show_message_dialog(gtk.MESSAGE_ERROR, "Faild to update FB\n%s"%e)
            return True

        return True


    def on_ctrl_scale_value_changed(self, adjust):
        openmv.set_attr(adjust.attr, int(adjust.value))

    def open_file(self, widget):
        dialog = gtk.FileChooserDialog(title=None,action=gtk.FILE_CHOOSER_ACTION_OPEN,
                buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        dialog.set_default_response(gtk.RESPONSE_OK)
        dialog.set_current_folder("./examples/")
        ff = gtk.FileFilter()
        ff.set_name("python")
        ff.add_pattern("*.py")
        dialog.add_filter(ff)

        if dialog.run() == gtk.RESPONSE_OK:
            with open(dialog.get_filename(), "r") as file:
                self.buffer.set_text(file.read())
                self.file_path=dialog.get_filename()
                self.save_button.set_sensitive(False)
                self.window.set_title(os.path.basename(self.file_path))

        dialog.destroy()

    def save_template(self, widget):
        self.da_menu.hide()
        x = self.x1
        y = self.y1
        w = self.x2-self.x1
        h = self.y2-self.y1

        entry = self.builder.get_object("template_entry")
        image = self.builder.get_object("template_image")
        image.set_from_pixbuf(self.pixbuf.subpixbuf(x, y, w, h))

        dialog = self.builder.get_object("save_template_dialog")
        dialog.set_transient_for(self.window);
        #dialog.set_default_response(gtk.RESPONSE_OK)

        if dialog.run() == gtk.RESPONSE_OK:
            openmv.save_template(x/SCALE, y/SCALE, w/SCALE, h/SCALE, entry.get_text()) #Use Scale
        dialog.hide()

    def save_descriptor(self, widget):
        self.da_menu.hide()
        x = self.x1
        y = self.y1
        w = self.x2-self.x1
        h = self.y2-self.y1

        entry = self.builder.get_object("desc_entry")
        image = self.builder.get_object("desc_image")
        image.set_from_pixbuf(self.pixbuf.subpixbuf(x, y, w, h))

        dialog = self.builder.get_object("save_descriptor_dialog")
        dialog.set_transient_for(self.window);
        #dialog.set_default_response(gtk.RESPONSE_OK)

        if dialog.run() == gtk.RESPONSE_OK:
            #if not entry.get_text():
            openmv.save_descriptor(x/SCALE, y/SCALE, w/SCALE, h/SCALE, entry.get_text()) #Use Scale
        dialog.hide()

    def save_file(self, widget):
        with open(self.file_path, "w") as file:
            file.write(self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter()))

    def save_file_as(self, widget):
        dialog = gtk.FileChooserDialog(title=None,action=gtk.FILE_CHOOSER_ACTION_SAVE,
                buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        dialog.set_default_response(gtk.RESPONSE_OK)
        dialog.set_current_folder("./examples/")
        ff = gtk.FileFilter()
        ff.set_name("python")
        ff.add_pattern("*.py")
        dialog.add_filter(ff)

        if dialog.run() == gtk.RESPONSE_OK:
            with open(dialog.get_filename(), "w") as file:
                file.write(self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter()))

        dialog.destroy()

    def text_changed(self, widget):
        self.save_button.set_sensitive(True)

    def quit(self, widget):
        # disconnect
        self.disconnect()

        # write last opened file
        with open(config_path, "w") as file:
            file.write(self.file_path)

        # exit
        sys.exit(0)

if __name__ == "__main__":
    omvgtk = OMVGtk()
    omvgtk.window.show_all()
    gobject.gobject.idle_add(omvgtk.update_drawing);
    gtk.main()
