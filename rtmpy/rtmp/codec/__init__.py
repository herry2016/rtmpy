# -*- test-case-name: rtmpy.tests.test_codec -*-
#
# Copyright (c) 2007-2009 The RTMPy Project.
# See LICENSE for details.

"""
RTMP codecs. Encoders and decoders for rtmp streams.

@see: U{RTMP (external)<http://rtmpy.org/wiki/RTMP>}
@since: 0.1
"""

from twisted.internet import task

from rtmpy import util
from rtmpy.rtmp import interfaces
from rtmpy.rtmp.codec import header


class DecodeError(Exception):
    """
    Raised if there is an error decoding an RTMP bytestream.
    """


class EncodeError(Exception):
    """
    Raised if there is an error encoding an RTMP bytestream.
    """


class BaseCodec(object):
    """
    @ivar deferred: The deferred from the result of L{getJob}.
    @type deferred: L{twisted.internet.defer.Deferred}
    @ivar job: A L{task.LoopingCall} instance that is used to iteratively
        call the method supplied by L{getJob}.
    """

    def __init__(self, manager):
        if not interfaces.IChannelManager.providedBy(manager):
            raise TypeError('IChannelManager expected (got %s)' % (type(manager),))

        self.manager = manager
        self.deferred = None
        self.buffer = util.BufferedByteStream()

        self.job = task.LoopingCall(self.getJob())

    def __del__(self):
        if not hasattr(self, 'job'):
            return

        if self.job.running:
            self.job.stop()

    def getJob(self):
        """
        Returns the method to be iteratively called to process the codec.

        This method is intended to be implemented by sub-classes.
        """
        raise NotImplementedError()

    def start(self, when=0):
        """
        Starts or resumes the job. If the job is already running (i.e. not
        stopped) then this is a noop.

        @return: The deferred from starting the job.
        @rtype: L{twisted.internet.defer.Deferred}
        """
        if self.job.running:
            return self.deferred

        self.deferred = self.job.start(when)

        return self.deferred

    def pause(self):
        """
        Pauses the codec. Called when the buffer is exhausted. If the job is
        already stopped then this is a noop.
        """
        if self.job.running:
            self.job.stop()
            self.deferred = None


class Decoder(BaseCodec):
    """
    Decodes an RTMP stream. De-interlaces the channels and writes the frames
    to the individual buffers.

    @ivar currentChannel: The channel currently being decoded.
    @type currentChannel: L{interfaces.IChannel}
    """

    def __init__(self, manager):
        BaseCodec.__init__(self, manager)

        self.currentChannel = None

    def getJob(self):
        return self.decode

    def readHeader(self):
        headerPosition = self.buffer.tell()

        try:
            return header.decodeHeader(self.buffer)
        except EOFError:
            self.buffer.seek(headerPosition)

            return None

    def getBytesAvailableForChannel(self, channel):
        """
        Returns the number of bytes available in the buffer to be read as an
        RTMP stream.
        """
        return min(
            self.buffer.remaining(),
            channel.frameRemaining
        )

    def readFrame(self):
        """
        This function attempts to read a frame from the stream. A frame is a
        set amount of data that borders header bytes. If a full frame was read
        from the buffer then L{currentChannel} is set to C{None}.

        After this function is finished, the next part of the buffer will
        either be empty or a header section.
        """
        if self.currentChannel is None:
            raise DecodeError('Channel is required to read frame')

        available = self.getBytesAvailableForChannel(self.currentChannel)
        frames = self.currentChannel.frames

        if available == 0:
            return

        self.currentChannel.write(self.buffer.read(available))

        if self.currentChannel.frames != frames:
            # a complete frame was read from the stream which means a new
            # header and frame body will be next in the stream
            self.currentChannel = None

    def canContinue(self, minBytes=1):
        """
        Checks to see if decoding can continue. If there are less bytes in the
        stream than C{minBytes} then the job is paused.

        @param minBytes: The minimum number of bytes required to continue
            decoding.
        @type minBytes: C{int}
        @rtype: C{bool}
        """
        remaining = self.buffer.remaining()

        if remaining < minBytes or remaining == 0:
            self.pause()

        return (remaining >= minBytes)

    def _decode(self):
        if self.current_channel is not None:
            self.readFrame()

        if not self.canContinue():
            # the buffer is empty
            return

        header = self.readHeader()

        if header is None:
            # not enough bytes left in the stream to continue decoding, we
            # require a complete header to decode
            return

        self.currentChannel = self.manager.getChannel(channelId)

        if header is not None:
            channel.setHeader(header)

        self.readFrame()

    def decode(self):
        """
        Attempt to decode the buffer.
        """
        if not self.canContinue():
            return

        # start from the beginning of the buffer
        self.buffer.seek(0)

        try:
            self._decode()
        except:
            self.deferred.errback()
        else:
            # delete the bytes that have already been decoded
            self.buffer.consume()

    def dataReceived(self, data):
        """
        Adds data to the end of the stream.
        """
        self.buffer.seek(0, 2)
        self.buffer.write(data)


class ChannelConsumer(object):
    def __init__(self, channel):
        self.buffer = util.BufferedByteStream()
        self.channel = channel
        self.header = None

        self.channel.registerConsumer(self)

    def write(self, data):
        self.buffer.append(data)

    def getData(self, length=0):
        data = self.buffer.read(length)
        self.buffer.consume()

        return data


class ProtocolEncoder(BaseCodec):
    """
    Interlaces all active channels to form one stream. At this point no
    attempt has been made to prioritise other channels over others.
    """

    def getJob(self):
        return task.LoopingCall(self.encode)

    def getRelativeHeader(self, old, new):
        if old is None or new.relative is False:
            return new

        return header.diffHeaders(old, new)

    def getNextChannel(self):
        """
        """

    def writeFrame(self, channel):
        """
        """
        meta = self.getChannelMeta(channel)
        available = min(
            meta.remaining(),
            channel.frameRemaining,
            # include protocol frame size here
        )

        if not meta.hasEnoughData(available):
            return False

        relativeHeader = self.getRelativeHeader(meta.header, channel.header)
        meta.header = channel.header

        header.encodeHeader(self.buffer, relativeHeader)
        self.buffer.write(meta.getData(available))

        return True

    def encode(self):
        def _encode():
            channel = self.getNextChannel()

            if channel is None:
                self.pauseProducing()

                return

            if self.writeFrame(channel):
                self.consumer.write(self.buffer.getvalue())
                self.buffer.truncate()

        try:
            _encode()
        except:
            self.deferred.errback()