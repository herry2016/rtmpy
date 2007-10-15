# -*- encoding: utf8 -*-
#
# Copyright (c) 2007 The RTMPy Project. All rights reserved.
# 
# Arnar Birgisson
# Thijs Triemstra
# 
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
# 
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
#
# AMF parser
# sources:
#   http://www.vanrijkom.org/archives/2005/06/amf_format.html
#   http://osflash.org/documentation/amf/astypes

import datetime
from types import *

try:
    import xml.etree.ElementTree as ET
except ImportError:
    try:
        import cElementTree as ET
    except ImportError:
        import elementtree.ElementTree as ET

from rtmpy import util
from rtmpy.util import BufferedByteStream

class AMF0Types:
    NUMBER      = 0x00
    BOOL        = 0x01
    STRING      = 0x02
    OBJECT      = 0x03
    MOVIECLIP   = 0x04
    NULL        = 0x05
    UNDEFINED   = 0x06
    REFERENCE   = 0x07
    MIXEDARRAY  = 0x08
    OBJECTTERM  = 0x09
    ARRAY       = 0x0a
    DATE        = 0x0b
    LONGSTRING  = 0x0c
    UNSUPPORTED = 0x0e
    XML         = 0x0f
    TYPEDOBJECT = 0x10
    AMF3        = 0x11

class AMF0Parser:

    def __init__(self, data):
        self.obj_refs = list()
        if isinstance(data, BufferedByteStream):
            self.input = data
        else:
            self.input = BufferedByteStream(data)

    def readElement(self):
        """Reads the data type."""
        type = self.input.read_uchar()
        if type == AMF0Types.NUMBER:
            """Reads a Number. In ActionScript 1 and 2 Number type
               represents all numbers, both floats and integers."""
            return self.input.read_double()

        elif type == AMF0Types.BOOL:
            return bool(self.input.read_uchar())

        elif type == AMF0Types.STRING:
            return self.readString()

        elif type == AMF0Types.OBJECT:
            return self.readObject()

        elif type == AMF0Types.MOVIECLIP:
            raise NotImplementedError()

        elif type == AMF0Types.NULL:
            return None

        elif type == AMF0Types.UNDEFINED:
            # TODO: do we need a special value here?
            return None

        elif type == AMF0Types.REFERENCE:
            return self.readReference()

        elif type == AMF0Types.MIXEDARRAY:
            """Returns an array"""
            len = self.input.read_ulong()
            obj = self.readObject()
            for key in obj.keys():
                try:
                    ikey = int(key)
                    obj[ikey] = obj[key]
                    del obj[key]
                except ValueError:
                    pass
            return obj

        elif type == AMF0Types.ARRAY:
            len = self.input.read_ulong()
            obj = []
            self.obj_refs.append(obj)
            obj.extend(self.readElement() for i in xrange(len))
            return obj

        elif type == AMF0Types.DATE:
            return readDate()

        elif type == AMF0Types.LONGSTRING:
            return self.readLongString()

        elif type == AMF0Types.UNSUPPORTED:
            # TODO: do we need a special value?
            return None

        elif type == AMF0Types.XML:
            return self.readXML()

        elif type == AMF0Types.TYPEDOBJECT:
            classname = readString()
            obj = readObject()
            # TODO do some class mapping?
            return obj

        elif type == AMF0Types.AMF3:
            p = AMF3Parser(self.input)
            return p.readElement()

        else:
            raise ValueError("Unknown AMF0 type 0x%02x at %d" % (type, self.input.tell()-1))

    def readString(self):
        len = self.input.read_ushort()
        return self.input.read_utf8_string(len)

    def readObject(self):
        obj = dict()
        self.obj_refs.append(obj)
        key = self.readString()
        while self.input.peek() != chr(AMF0Types.OBJECTTERM):
            obj[key] = self.readElement()
            key = self.readString()
        self.input.read(1) # discard the end marker (AMF0Types.OBJECTTERM = 0x09)
        return obj
    
    def readReference(self):
        idx = self.input.read_ushort()
        return self.obj_refs[idx]

    def readDate(self):
        """Reads a date.
        Date: 0x0B T7 T6 .. T0 Z1 Z2 T7 to T0 form a 64 bit Big Endian number
        that specifies the number of nanoseconds that have passed since
        1/1/1970 0:00 to the specified time. This format is UTC 1970. Z1 an
        Z0 for a 16 bit Big Endian number indicating the indicated time's
        timezone in minutes."""
        ms = self.input.read_double()
        tz = self.input.read_short()
        class TZ(datetime.tzinfo):
            def utcoffset(self, dt):
                return datetime.timedelta(minutes=tz)
            def dst(self,dt):
                return None
            def tzname(self,dt):
                return None
        return datetime.datetime.fromtimestamp(ms/1000.0, TZ())
    
    def readLongString(self):
        len = self.input.read_ulong()
        return self.input.read_utf8_string(len)

    def readXML(self):
        data = readLongString()
        return ET.fromstring(data)

class AMF0Encoder:
    
    type_map = [
        ((bool,), "writeBoolean"),
        ((int,long,float), "writeNumber"), # Maybe add decimal ?
        ((StringTypes,), "writeString"),
        ((InstanceType,), "writeObject"),
        ((datetime.date, datetime.datetime), "writeDate"),
        ((ET._ElementInterface,), "writeXML"),
    ]

    def __init__(self, output):
        """Constructs a new AMF0Encoder. output should be a writable
        file-like object."""
        self.output = output
        self.obj_refs = []
        
    def writeElement(self, data):
        """Writes the data."""
        for tlist, method in self.type_map:
            for t in tlist:
                if isinstance(data, t):
                    return getattr(self, method)(data)
    
    def writeNumber(self, n):
        self.output.write_uchar(AMF0Types.NUMBER)
        self.output.write_double(float(n))
    
    def writeBoolean(self, b):
        self.output.write_uchar(AMF0Types.BOOL)
        if b:
            self.output.write_uchar(1)
        else:
            self.output.write_uchar(0)
    
    def writeString(self, s, writeType=True):
        s = unicode(s).encode('utf8')
        if len(s) > 0xffff:
            if writeType:
                self.output.write_uchar(AMF0Types.LONGSTRING)
            self.output.write_ulong(len(s))
        else:
            if writeType:
                self.output.write_uchar(AMF0Types.STRING)
            self.output.write_ushort(len(s))
        self.output.write(s)
    
    def writeObject(self, o):
        if o in self.obj_refs:
            self.output.write_uchar(AMF0Types.REFERENCE)
            self.output.write_ushort(self.obj_refs.index(o))
        else:
            self.obj_refs.append(o)
            self.output.write_uchar(AMF0Types.OBJECT)
            o = o.__dict_ # TODO: give objects a chance of controlling what we send
            for key, val in o.items():
                self.writeString(key, False)
                self.writeElement(o)
            self.writeString("", False)
            self.output.write_uchar(AMF0Types.OBJECTTERM)
    
    def writeDate(self, d):
        if isinstance(d, datetime.date):
            d = datetime.datetime.combine(d, datetime.time(0))
        self.output.write_uchar(AMF0Types.DATE)
        ms = time.mktime(d.timetuple)
        if d.tzinfo:
            tz = d.tzinfo.utcoffset.days*1440 + d.tzinfo.utcoffset.seconds/60
        else:
            tz = 0
        self.output.write_double(ms)
        self.output.write_short(tz)
    
    def writeXML(self, e):
        self.output.write_uchar(AMF0Types.XML)
        data = ET.tostring(e, 'utf8')
        self.output.write_ulong(len(data))
        self.output.write(data)

class AMF3Types:
    UNDEFINED       =           0x00
    NULL            =           0x01
    BOOL_FALSE      =           0x02
    BOOL_TRUE       =           0x03
    INTEGER         =           0x04
    NUMBER          =           0x05
    STRING          =           0x06
    # TODO: not defined on site, says it's only XML type,
    # so we'll assume it is for the time being..
    XML             =           0x07
    DATE            =           0x08
    ARRAY           =           0x09
    OBJECT          =           0x0a
    XMLSTRING       =           0x0b
    BYTEARRAY       =           0x0c
    # Unkown        =           0x0d   

class AMF3ObjectTypes:
    # Property list encoding.
    # The remaining integer-data represents the number of
    # class members that exist. The property names are read
    # as string-data. The values are then read as AMF3-data.
    PROPERTY = 0x00

    # Externalizable object.
    # What follows is the value of the "inner" object,
    # including type code. This value appears for objects
    # that implement IExternalizable, such as
    # ArrayCollection and ObjectProxy.
    EXTERNALIZABLE = 0x01
    
    # Name-value encoding.
    # The property names and values are encoded as string-data
    # followed by AMF3-data until there is an empty string
    # property name. If there is a class-def reference there
    # are no property names and the number of values is equal
    # to the number of properties in the class-def.
    VALUE = 0x02
    
    # Proxy object
    PROXY = 0x03

class AMF3Parser:

    def __init__(self, data):
        self.obj_refs = list()
        self.str_refs = list()
        self.class_refs = list()
        if isinstance(data, BufferedByteStream):
            self.input = data
        else:
            self.input = BufferedByteStream(data)

    def readElement(self):
        type = self.input.read_uchar()
        if type == AMF3Types.UNDEFINED:
            return None
        
        if type == AMF3Types.NULL:
            return None
        
        if type == AMF3Types.BOOL_FALSE:
            return False
        
        if type == AMF3Types.BOOL_TRUE:
            return True
        
        if type == AMF3Types.INTEGER:
            return self.readInteger()
        
        if type == AMF3Types.NUMBER:
            return self.input.read_double()
        
        if type == AMF3Types.STRING:
            return self.readString()
        
        if type == AMF3Types.XML:
            return self.readXML()
        
        if type == AMF3Types.DATE:
            return self.readDate()
        
        if type == AMF3Types.ARRAY:
            return self.readArray()
        
        if type == AMF3Types.OBJECT:
            return self.readObject()
        
        if type == AMF3Types.XMLSTRING:
            return self.readString(use_references=False)
        
        if type == AMF3Types.BYTEARRAY:
            raise self.readByteArray()
        
        else:
            raise ValueError("Unknown AMF3 datatype 0x%02x at %d" % (type, self.input.tell()-1))
    
    def readInteger(self):
        # see http://osflash.org/amf3/parsing_integers for AMF3 integer data format
        n = 0
        b = self.input.read_uchar()
        result = 0
        
        while b & 0x80 and n < 3:
            result <<= 7
            result |= b & 0x7f
            b = self.input.read_uchar()
            n += 1
        if n < 3:
            result <<= 7
            result |= b
        else:
            result <<= 8
            result |= b
        if result & 0x10000000:
            result |= 0xe0000000
            
        # return a converted integer value
        return result
    
    def readString(self, use_references=True):
        length = self.readInteger()
        if use_references and length & 0x01 == 0:
            return self.str_refs[length >> 1]
        
        length >>= 1
        buf = self.input.read(length)
        try:
            # Try decoding as regular utf8 first since that will
            # cover most cases and is more efficient.
            # XXX: I'm not sure if it's ok though.. will it always raise exception?
            result = unicode(buf, "utf8")
        except UnicodeDecodeError:
            result = util.decode_utf8_modified(buf)
        
        if use_references and len(result) != 0:
            self.str_refs.append(result)
        
        return result
    
    def readXML(self):
        data = self.readString(False)
        return ET.fromstring(data)
    
    def readDate(self):
        ref = self.readInteger()
        if ref & 0x01 == 0:
            return self.obj_refs[ref >> 1]
        ms = self.input.read_double()
        result = datetime.datetime.fromtimestamp(ms/1000.0)
        self.obj_refs.append(result)
        return result
    
    def readArray(self):
        size = self.readInteger()
        if size & 0x01 == 0:
            return self.obj_refs[size >> 1]
        size >>= 1
        key = self.readString()
        if key == "":
            # integer indexes only -> python list
            result = []
            self.obj_refs.append(result)
            for i in xrange(size):
                el = self.readElement()
                result.append(el)
        else:
            # key,value pairs -> python dict
            result = {}
            self.obj_refs.append(result)
            while key != "":
                el = self.readElement()
                result[key] = el
                key = self.readString()
            for i in xrange(size):
                el = self.readElement()
                result[i] = el
        
        return result
    
    def readObject(self):
        type = self.readInteger()
        if type & 0x01 == 0:
            return self.obj_refs[type >> 1]
        class_ref = (type >> 1) & 0x01 == 0
        type >>= 2
        if class_ref:
            class_ = self.class_refs[type]
        else:
            class_ = AMF3Class()
            class_.name = self.readString()
            class_.encoding = type & 0x03
            class_.attrs = []
        
        type >>= 2
        
        if class_.name:
            # TODO : do some class mapping?
            obj = AMF3Object(class_)
        else:
            obj = AMF3Object()
        
        self.obj_refs.append(obj)
        
        if class_.encoding & AMF3ObjectTypes.EXTERNALIZABLE:
            if not class_ref:
                self.class_refs.append(class_)
            # TODO: implement externalizeable interface here
            obj.__amf_externalized_data = self.readElement()
        else:
            if class_.encoding & AMF3ObjectTypes.VALUE:
                if not class_ref:
                    self.class_refs.append(class_)
                attr = self.readString()
                while attr != "":
                    class_.attrs.append(attr)
                    setattr(obj, attr, self.readElement())
                    attr = self.readString()
            else:
                if not class_ref:
                    for i in range(type):
                        class_.attrs.append(self.readString())
                    self.class_refs.append(class_)
                for attr in class_.attrs:
                    setattr(obj, attr, self.readElement())
        
        return obj

    def readByteArray(self):
        length = self.readInteger()
        return self.input.read(length >> 1)

class AMF3Class:
    def __init__(self, name=None, encoding=None, attrs=None):
        self.name = name
        self.encoding = encoding
        self.attrs = attrs

class AMF3Object:
    def __init__(self, class_=None):
        self.__amf_class = class_
    
    def __repr__(self):
        return "<AMF3Object [%s] at 0x%08X>" % (
            self.__amf_class and self.__amf_class.name or "no class",
            id(self))

class AMFMessageParser:
    
    def __init__(self, data):
        self.input = BufferedByteStream(data)
    
    def parse(self):
        msg = AMFMessage()
        # The first byte of the AMF file/stream is either 0×00 or 0×03.
        msg.amfVersion = self.input.read_uchar()
        if msg.amfVersion == 0:
            # AMF0
            parser_class = AMF0Parser
        elif msg.amfVersion == 3:
            # AMF3
            parser_class = AMF3Parser
        else:
            raise Exception("Invalid AMF version: " + str(msg.amfVersion))
        # The second byte is a client byte, which is set to:
        # - 0×00 for Flash Player 8 and below
        # - 0×01 for FlashCom/FMS
        # - 0×03 for Flash Player 9
        msg.clientType = self.input.read_uchar()
        # The third and fourth bytes form an integer value that specifies
        # the number of headers.
        header_count = self.input.read_short()
        # Headers are used to request debugging information, send 
        # authentication info, tag transactions, etc.
        for i in range(header_count):
            header = AMFMessageHeader()
            # UTF string (including length bytes) - header name.
            name_len = self.input.read_ushort()
            header.name = self.input.read_utf8_string(name_len)
            # Specifies if understanding the header is "required".
            header.required = bool(self.input.read_uchar())
            # Long - Length in bytes of header.
            msg.length = self.input.read_ulong()
            # Variable - Actual data (including a type code).
            header.data = parser_class(self.input).readElement()
            msg.headers.append(header)
        # Between the headers and the start of the bodies is a int 
        # specifying the number of bodies.
        bodies_count = self.input.read_short()
        # A single AMF envelope can contain several requests/bodies; 
        # AMF supports batching out of the box.
        for i in range(bodies_count):
            body = AMFMessageBody()
            # The target may be one of the following:
            # - An http or https URL. In that case the gateway should respond 
            #   by sending a SOAP request to that URL with the specified data. 
            #   In that case the data will be an Array and the first key 
            #   (data[0]) contains the parameters to be sent.
            # - A string with at least one period (.). The value to the right 
            #   of the right-most period is the method to be called. The value 
            #   to the left of that is the service to be invoked including package 
            #   name. In that case data will be an Array of arguments to be sent 
            #   to the method.
            target_len = self.input.read_ushort()
            body.target = self.input.read_utf8_string(target_len)
            # The response is a string that gives the body an id so it can be 
            # tracked by the client.
            response_len = self.input.read_ushort()
            body.response = self.input.read_utf8_string(response_len)
            # Body length in bytes.
            body.length = self.input.read_ulong()
            # Actual data (including a type code).
            body.data = parser_class(self.input).readElement()
            # Bodies contain actual Remoting requests and responses.
            msg.bodies.append(body)
        # Return Python object.
        return msg
    
class AMFMessageEncoder:

    def __init__(self, headers, bodies):
        self.bodies = bodies
        self.headers = headers
        self.output = BufferedByteStream()
    
    def encode(self):
        #
        encoder_class = AMF0Encoder
        # Write AMF version.
        self.output.write_short(0)
        # Write header length.
        header_count = len(self.headers)
        self.output.write_short(header_count)
        # Write headers.
        for header in self.headers:
            # Write header name.
            self.output.write_utf8_string(header.name)
            # Write header requirement.
            self.output.write_uchar(bool(header.required))
            # Write length in bytes of header.
            self.output.write_ulong(-1)
            # Header data.
            encoder_class(self.output).writeElement(header.data)
        # Write bodies length.
        bodies_count = len(self.bodies)
        self.output.write_short(bodies_count)
        # Write bodies.
        for body in self.bodies:
            # Target (/1/onResult).
            self.output.write_utf8_string(body.target)
            # Response (null).
            self.output.write_utf8_string(body.response)
            # Body length in bytes.
            self.output.write_ulong(-1)
            # Actual Python result data.
            encoder_class(self.output).writeElement(body.data)
        # Return AMF data.
        return self.output
    
class AMFMessage:
    
    def __init__(self):
        # AMF version (0 or 3)
        self.amfVersion = None
        # The client type can be set to:
        # - 0×00 for Flash Player 8 and below.
        # - 0×01 for FlashCom/FMS.
        # - 0×03 for Flash Player 9.
        self.clientType = None
        # Headers are used to request debugging information, send 
        # authentication info, tag transactions, etc.
        self.headers = []
        # A single AMF message can contain several requests/bodies.
        self.bodies = []
    
    def __repr__(self):
        r = "<AMFMessage version=" + str(self.amfVersion) + " type=" + str(self.clientType) + "\n"
        for h in self.headers:
            r += "   " + repr(h) + "\n"
        for b in self.bodies:
            r += "   " + repr(b) + "\n"
        r += ">"
        return r

class AMFMessageHeader:
    
    def __init__(self):
        # UTF string (including length bytes) - name.
        self.name = None
        # Boolean - specifies if understanding the header is "required".
        self.required = None
        # Long - Length in bytes of header.
        self.length = None
        # Variable - Actual data (including a type code).
        self.data = None
    
    def __repr__(self):
        return "<AMFMessageHeader %s = %r>" % (self.name, self.data)

class AMFMessageBody:
    
    def __init__(self):
        # UTF String - Target.
        self.target = None
        # UTF String - Response.
        self.response = None
        # Long - Body length in bytes.
        self.length = None
        # Variable - Actual data (including a type code).
        self.data = None

    def __repr__(self):
        return "<AMFMessageBody target=%s data= %r>" % (self.target, self.data)
    
if __name__ == "__main__":
    import sys, glob
    debug = False
    print "Starting AMF parser..."
    for arg in sys.argv[1:]:
        if arg == 'debug':
            debug = True
        for fname in glob.glob(arg):
            f = file(fname, "r")
            data = f.read()
            size = str(f.tell())
            f.close()
            p = AMFMessageParser(data)
            #print "=" * 40
            print "Parsing file", fname.rsplit("\\",1)[-1], 
            try:
                obj = p.parse()
            except:
                raise
                print "   ---> FAILED"
            else:
                print "   ---> OK"
                if debug:
                    print repr(obj)
            
