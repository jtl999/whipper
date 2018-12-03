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

_TRACK_RE = re.compile("^Analyzing track (?P<track>[0-9]*) \(AUDIO\): start (?P<start>[0-9]*:[0-9]*:[0-9]*), length (?P<length>[0-9]*:[0-9]*:[0-9]*)")
_CRC_RE = re.compile("Found (?P<channels>[0-9]*) Q sub-channels with CRC errors")
_BEGIN_CDRDAO_RE = re.compile("-"*60)
_LAST_TRACK_RE = re.compile("^(?P<track>[0-9]*)")
_LEADOUT_RE = re.compile("^Leadout AUDIO\s*[0-9]\s*[0-9]*:[0-9]*:[0-9]*\([0-9]*\)")

class ProgressParser:
    tracks = 0
    currentTrack = 0
    oldline = '' # for leadout/final track number detection
    def parse(self, line):
        cdrdao_m = _BEGIN_CDRDAO_RE.match(line)

        if cdrdao_m:
            logger.debug("RE: Begin cdrdao toc-read")

        leadout_m = _LEADOUT_RE.match(line)

        if leadout_m:
            logger.debug("RE: Reached leadout")
            last_track_m = _LAST_TRACK_RE.match(self.oldline)
            if last_track_m:
                self.tracks = last_track_m.group('track')
        track_s = _TRACK_RE.search(line)
        if track_s:
            logger.debug("RE: Began reading track: %d" % int(track_s.group('track')))
            self.currentTrack = int(track_s.group('track'))
        crc_s = _CRC_RE.search(line)
        if crc_s:
            sys.stdout.write("Track %d finished, found %d Q sub-channels with CRC errors\n" % (self.currentTrack, int(crc_s.group('channels'))) )

        self.oldline = line
        

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
        self._parser = ProgressParser()
        self.fd, self.tocfile = tempfile.mkstemp(suffix=u'.cdrdao.read-toc.whipper.task')
    def start(self, runner):
        task.Task.start(self, runner)
        ## TODO: Remove these hardcoded values (for testing)
        fast_toc = self.fast_toc
        device = self.device


        os.close(self.fd)
        os.unlink(self.tocfile)

        cmd = [CDRDAO, 'read-toc'] + (['--fast-toc'] if fast_toc else []) + [
            '--device', device, self.tocfile]
        
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
                self._parser.parse(line)
                if (self._parser.currentTrack is not 0 and self._parser.tracks is not 0):
                    progress = float('%d' % self._parser.currentTrack) / float(self._parser.tracks)
                    if progress < 1.0:
                        self.setProgress(progress)
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
        self.toc = TocFile(self.tocfile)
        self.toc.parse()
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
