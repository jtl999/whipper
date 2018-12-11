import os
import re
import shutil
import tempfile
import subprocess
import time
from subprocess import Popen, PIPE

from whipper.common.common import EjectError, truncate_filename
from whipper.image.toc import TocFile
from whipper.extern.task import task

import logging
logger = logging.getLogger(__name__)

CDRDAO = 'cdrdao'

class ReadTOC_Task(task.Task):
    """
    Task that reads the TOC of the disc using cdrdao
    """
    description = "Reading TOC"
    toc = None
    
    def __init__(self, device, fast_toc=False, toc_path=None):
        """
        Read the TOC for 'device'.
        @param device:  block device to read TOC from
        @type  device:  str
        @param fast_toc:  If to use fast-toc cdrdao mode
        @type  fast_toc: bool
        @param toc_path: Where to save TOC if wanted.
        @type  toc_path: str
        
        """
        
        self.device = device
        self.fast_toc = fast_toc
        self.toc_path = toc_path
        self._buffer = ""  # accumulate characters

    def start(self, runner):
        task.Task.start(self, runner)

        cmd = [CDRDAO, 'read-toc'] + (['--fast-toc'] if fast_toc else []) + [
            '--device', device, tocfile]

        self._popen = asyncsub.Popen(cmd,
                                     bufsize=bufsize,
                                     stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE,
                                     close_fds=True)
        def _read(self, runner):
            ret = self._popen.recv_err()
            if not ret:
                if self._popen.poll() is not None:
                    self._done()
                    return
                self.schedule(0.01, self._read, runner)
                return
            self._buffer += ret
            
            # parse buffer into lines if possible, and parse them
            if "\n" in self._buffer:
                lines = self._buffer.split('\n')
                if lines[-1] != "\n":
                    # last line didn't end yet
                    self._buffer = lines[-1]
                    del lines[-1]
                else:
                    self._buffer = ""

                for line in lines:
                    sys.stdout.write("%s\n" % line)

                progress = float(num) / float(den)
                if progress < 1.0:
                    self.setProgress(progress)
            
            # 0 does not give us output before we complete, 1.0 gives us output
            # too late
            
            self._start_time = time.time()
            self.schedule(1.0, self._read, runner)
        
    def _read(self, runner):
        ret = self._popen.recv_err()
        if not ret:
            if self._popen.poll() is not None:
                self._done()
                return
            self.schedule(0.01, self._read, runner)
            return
        self._buffer += ret

        # parse buffer into lines if possible, and parse them
        if "\n" in self._buffer:

            lines = self._buffer.split('\n')
            if lines[-1] != "\n":
                # last line didn't end yet
                self._buffer = lines[-1]
                del lines[-1]
            else:
                self._buffer = ""
            for line in lines:
                sys.stdout.write("%s\n" % line)

        # 0 does not give us output before we complete, 1.0 gives us output
        # too late
        self.schedule(0.01, self._read, runner)


    def _poll(self, runner):

        if self._popen.poll() is None:
            self.schedule(1.0, self._poll, runner)
            return

        self._done()


    def _done(self):
        end_time = time.time()
        self.setProgress(1.0)

        self.stop()
        return

def DetectCdr(device):
    """
    Return whether cdrdao detects a CD-R for 'device'.
    """
    cmd = [CDRDAO, 'disk-info', '-v1', '--device', device]
    logger.debug("executing %r", cmd)
    p = Popen(cmd, stdout=PIPE, stderr=PIPE)
    if 'CD-R medium          : n/a' in p.stdout.read():
        return False
    else:
        return True

def version():
    """
    Return cdrdao version as a string.
    """
    cdrdao = Popen(CDRDAO, stderr=PIPE)
    out, err = cdrdao.communicate()
    if cdrdao.returncode != 1:
        logger.warning("cdrdao version detection failed: "
                       "return code is " + str(cdrdao.returncode))
        return None
    m = re.compile(r'^Cdrdao version (?P<version>.*) - \(C\)').search(
        err.decode('utf-8'))
    if not m:
        logger.warning("cdrdao version detection failed: "
                       "could not find version")
        return None
    return m.group('version')

def getCDRDAOVersion():
    """
    stopgap morituri-insanity compatibility layer
    """
    return version()
