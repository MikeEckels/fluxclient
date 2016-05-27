
from tempfile import NamedTemporaryFile
from select import select
import mimetypes
import logging
import shlex
import os

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class RobotConsole(object):
    _mode = "standard"
    _thread = None
    _raw_sock = None

    def __init__(self, robot_obj):
        self.robot_obj = robot_obj
        self.simple_mapping = {
            "deviceinfo": robot_obj.deviceinfo,
            "start": robot_obj.start_play,
            "pause": robot_obj.pause_play,
            "resume": robot_obj.resume_play,
            "abort": robot_obj.abort_play,
            "report": robot_obj.report_play,
            "position": robot_obj.position,
            "quit": robot_obj.quit_task,
            "kick": robot_obj.kick,

            "scan": robot_obj.begin_scan,
            "scan_backward": robot_obj.scan_backward,
            "scan_next": robot_obj.scan_next,

            "maintain": robot_obj.begin_maintain,

            "home": robot_obj.maintain_home,
            "reset_mb": robot_obj.maintain_reset_mb,
            "headinfo": robot_obj.maintain_headinfo,
            "play": {
                "quit": robot_obj.quit_play
            }
        }

        self.cmd_mapping = {
            "ls": self.list_file,
            "fileinfo": self.fileinfo,
            "mkdir": self.mkdir,
            "rmdir": self.rmdir,
            "rmfile": self.rmfile,
            "cp": self.cpfile,
            "download": self.download_file,
            "upload": self.upload_file,
            "md5": self.md5,

            "select": self.select_file,
            "update_fw": self.update_fw,
            "update_mbfw": self.update_mbfw,
            "oneshot": self.oneshot,
            "scanimages": self.scanimages,
            "raw": self.raw_mode,
            "config": {
                "set": self.config_set,
                "get": self.config_get,
                "del": self.config_del
            },

            "eadj": self.maintain_eadj,
            "cor_h": self.maintain_hadj,
            "load_filament": self.maintain_load_filament,
            "stop_load_filament": self.maintain_stop_load_filament,
            "unload_filament": self.maintain_unload_filament,
            "extruder_temp": self.maintain_extruder_temp,
            "update_hbfw": self.maintain_update_hbfw,
            "play": {
                "info": self.play_info
            },
        }

    def call_command(self, ref, args, wrapper=None):
        if not args:
            return False
        cmd = args[0]
        if cmd in ref:
            obj = ref[cmd]
            if isinstance(obj, dict):
                return self.call_command(obj, args[1:], wrapper)
            else:
                if wrapper:
                    wrapper(obj, *args[1:])
                else:
                    obj(*args[1:])
                return True
        return False

    def on_cmd(self, arguments):
        if self._mode == "raw":
            if arguments == "quit":
                self.quit_raw_mode()
            else:
                self._raw_sock.send(arguments.encode() + b"\n")
        else:
            args = shlex.split(arguments)

            try:
                if self.call_command(self.simple_mapping, args,
                                     self.simple_cmd):
                    pass
                elif self.call_command(self.cmd_mapping, args):
                    pass
                else:
                    logger.error("Unknow Command: %s", arguments)

            except RuntimeError as e:
                logger.error("RuntimeError%s" % repr(e.args))

    def simple_cmd(self, func_ptr, *args):
        ret = func_ptr(*args)
        if ret:
            logger.info(ret)
        else:
            logger.info("ok")

    def list_file(self, args):
        path = shlex.split(args)[0]
        params = path.split("/", 1)

        for is_dir, node in self.robot_obj.list_files(*params):
            if is_dir:
                logger.info("DIR %s" % os.path.join(path, node))
            else:
                logger.info("FILE %s" % os.path.join(path, node))
        logger.info("ls done.")

    def select_file(self, path):
        path = shlex.split(path)[0]
        entry, filename = path.split("/", 1)
        self.simple_cmd(self.robot_obj.select_file, entry, filename)

    def fileinfo(self, path):
        path = shlex.split(path)[0]
        entry, filename = path.split("/", 1)
        info, images = self.robot_obj.fileinfo(entry, filename)
        logger.info("%s" % info)

        previews = []
        for img in images:
            ext = mimetypes.guess_extension(img[0])
            if ext:
                ntf = NamedTemporaryFile(suffix=ext, delete=False)
                ntf.write(img[1])
                previews.append(ntf.name)
        if previews:
            os.system("open " + " ".join(previews))

    def mkdir(self, path):
        path = shlex.split(path)[0]
        if path.startswith("SD/"):
            self.simple_cmd(self.robot_obj.mkdir, "SD", path[3:])
        else:
            raise RuntimeError("NOT_SUPPORT", "SD_ONLY")

    def rmdir(self, path):
        path = shlex.split(path)[0]
        if path.startswith("SD/"):
            self.simple_cmd(self.robot_obj.rmdir, "SD", path[3:])
        else:
            raise RuntimeError("NOT_SUPPORT", "SD_ONLY")

    def rmfile(self, path):
        path = shlex.split(path)[0]
        if path.startswith("SD/"):
            self.simple_cmd(self.robot_obj.rmfile, "SD", path[3:])
        else:
            raise RuntimeError("NOT_SUPPORT", "SD_ONLY")

    def cpfile(self, source, target):
        try:
            if source.startswith("SD/"):
                source_entry = "SD"
                source = source[3:]
            elif source.startswith("USB/"):
                source_entry = "USB"
                source = source[4:]
            else:
                raise RuntimeError("NOT_SUPPORT", "BAD_ENTRY")

            if target.startswith("SD/"):
                target = target[3:]
                self.simple_cmd(self.robot_obj.cpfile, source_entry, source,
                                "SD", target)
            else:
                raise RuntimeError("NOT_SUPPORT", "SD_ONLY")
        except ValueError:
            raise RuntimeError("BAD_PARAMS")

    def download_file(self, source, target):
        def callback(left, size):
            logger.info("Download %i / %i" % (size - left, size))

        entry, path = source.split("/", 1)
        with open(target, "wb") as f:
            self.robot_obj.download_file(entry, path, f, callback)

    def upload_file(self, source, upload_to="#"):
        self.robot_obj.upload_file(
            source, upload_to, progress_callback=self.log_progress_callback)

    def update_fw(self, filename):
        self.robot_obj.upload_file(
            filename.rstrip(), cmd="update_fw",
            progress_callback=self.log_progress_callback)

    def update_mbfw(self, filename):
        self.robot_obj.upload_file(
            filename.rstrip(), cmd="update_mbfw",
            progress_callback=self.log_progress_callback)

    def md5(self, filename):
        entry, path = filename.split("/", 1)
        md5 = self.robot_obj.md5(entry, path)
        logger.info("MD5 %s %s", filename, md5)

    def play_info(self):
        metadata, images = self.robot_obj.play_info()
        logger.info("Metadata:")
        for k, v in metadata.items():
            logger.info("  %s=%s", k, v)
        tempfiles = []
        if images:
            for mime, buf in images:
                ext = mimetypes.guess_extension(mime)
                if ext:
                    ntf = NamedTemporaryFile(suffix=".jpg", delete=False)
                    ntf.write(buf)
                    tempfiles.append(ntf)
            os.system("open " + " ".join([n.name for n in tempfiles]))

    def oneshot(self, filename=None):
        images = self.robot_obj.oneshot()
        tempfiles = []
        for mime, buf in images:
            ext = mimetypes.guess_extension(mime)
            if ext:
                ntf = NamedTemporaryFile(suffix=".jpg", delete=False)
                ntf.write(buf)
                tempfiles.append(ntf)

        os.system("open " + " ".join([n.name for n in tempfiles]))

    def scanimages(self, filename=None):
        images = self.robot_obj.scanimages()
        tempfiles = []
        for mime, buf in images:
            ext = mimetypes.guess_extension(mime)
            if ext:
                ntf = NamedTemporaryFile(suffix=".jpg", delete=False)
                ntf.write(buf)
                tempfiles.append(ntf)

        os.system("open " + " ".join([n.name for n in tempfiles]))

    def config_set(self, key, value):
        self.robot_obj.config_set(key, value)
        logger.info("ok")

    def config_get(self, key):
        value = self.robot_obj.config_get(key)
        if value:
            logger.info("%s=%s\nok" % (key, value))
        else:
            logger.info("%s not set\nok" % key)

    def config_del(self, key):
        self.robot_obj.config_del(key)
        logger.info("ok")

    def maintain_eadj(self, ext=None):
        def callback(nav):
            logger.info("Mainboard info: %s", nav)

        if ext == "clean":
            ret = self.robot_obj.maintain_eadj(navigate_callback=callback,
                                               clean=True)
        else:
            ret = self.robot_obj.maintain_eadj(navigate_callback=callback)

        data_str = ", ".join(("%.4f" % i for i in ret))
        logger.info("Data: %s, Error: %.4f", data_str, (max(*ret) - min(*ret)))
        logger.info("ok")

    def maintain_hadj(self, h=None):
        def callback(nav):
            logger.info("Mainboard info: %s", nav)

        if h is None:
            ret = self.robot_obj.maintain_hadj(navigate_callback=callback)
        else:
            ret = self.robot_obj.maintain_hadj(navigate_callback=callback,
                                               manual_h=float(h))

        logger.info("Data: %s", ret)
        logger.info("ok")

    def maintain_load_filament(self, index, temp):
        def callback(nav):
            logger.info("NAV: %s", nav)

        self.robot_obj.maintain_load_filament(int(index), float(temp),
                                              callback)
        logger.info("ok")

    def maintain_stop_load_filament(self):
        self.robot_obj.maintain_stop_load_filament()

    def maintain_unload_filament(self, index, temp):
        def callback(nav):
            logger.info("NAV: %s", nav)

        self.robot_obj.maintain_unload_filament(int(index), float(temp),
                                                callback)
        logger.info("ok")

    def maintain_extruder_temp(self, sindex, stemp):
        self.robot_obj.maintain_extruder_temp(int(sindex), float(stemp))
        logger.info("ok")

    def maintain_update_hbfw(self, filename):
        def callback(nav):
            logger.info("--> %s", nav)
        mimetype, _ = mimetypes.guess_type(filename)
        if not mimetype:
            mimetype = "binary"
        with open(filename, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            self.robot_obj.maintain_update_hbfw(mimetype, f, size, callback)
        logger.info("ok")

    def raw_mode(self):
        import threading
        self._raw_sock = self.robot_obj.raw_mode()
        self._mode = "raw"

        self._thread = threading.Thread(target=self.__raw_mode_thread)
        self._thread.setDaemon(True)
        self._thread.start()
        logger.info("raw mode ->")

    def quit_raw_mode(self):
        self._mode = "standard"
        self._raw_sock = None
        if self._thread:
            self._thread.join()

        logger.info(self.robot_obj.quit_raw_mode())

    def log_progress_callback(self, robot, progress, total):
        logger.info("Processing %3.1f %% (%i of %i)" %
                    (progress / total * 100.0, progress, total))

    def __raw_mode_thread(self):
        try:
            while self._mode == "raw":
                rl = select((self._raw_sock, ), (), (), 0.1)[0]
                if rl:
                    buf = rl[0].recv(4096)
                    if buf:
                        msg = buf.decode("utf8", "replace")
                        for ln in msg.split("\n"):
                            logger.info(ln.rstrip("\r\x00"))
                    else:
                        logger.error("Connection closed")
                        return

        except Exception:
            self._mode == "standard"
            logger.exception("Raw mode fatel, your session my be broken")