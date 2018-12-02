import os
import sys
import re
import shutil
import tempfile
import subprocess
import time
from subprocess import Popen, PIPE

from whipper.common.common import EjectError, truncate_filename
from whipper.image.toc import TocFile
from whipper.extern.task import task
from whipper.extern import asyncsub

import logging
logger = logging.getLogger(__name__)

CDRDAO = 'cdrdao'

_TRACK_RE = "^Analyzing track (?P<track>[0-9]*) \(AUDIO\): start (?P<start>[0-9]*:[0-9]*:[0-9]*), length (?P<length>[0-9]*:[0-9]*:[0-9]*)"
_CRC_RE = "Found (?P<errors>[0-9][0-9]) Q sub-channels with CRC errors"

class ProgressParser:
    def parse(self, line):
       pass 
        

class ReadTOC_Task(task.Task):
    """
    Task that reads the TOC of the disc using cdrdao
    """
    description = "Reading TOC"
    toc = None
    
    def __init__(self, device, fast_toc=False):
        """
        Read the TOC for 'device'.
        @device: path of device
        @type device: str
        @param fast_toc: use cdrdao fast-toc mode
        @type fast_toc: bool
        """
        
        self.device = device
        self.fast_toc = fast_toc
        self._buffer = ""  # accumulate characters

    def start(self, runner):
        task.Task.start(self, runner)
        ## TODO: Remove these hardcoded values (for testing)
        fast_toc = self.fast_toc
        device = self.device

        fd, tocfile = tempfile.mkstemp(suffix=u'.cdrdao.read-toc.whipper.task')
        os.close(fd)
        os.unlink(tocfile)

        cmd = [CDRDAO, 'read-toc'] + (['--fast-toc'] if fast_toc else []) + [
            '--device', device, tocfile]
        
        self._popen = asyncsub.Popen(cmd,
                                     bufsize=1024,
                                     stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE,
                                     close_fds=True)

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

        sys.stdout.write("_poll\n")
        if self._popen.poll() is None:
            self.schedule(1.0, self._poll, runner)
            return

        self._done()


    def _done(self):
        end_time = time.time()
        self.setProgress(1.0)

        self.stop()
        return

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
