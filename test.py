import OsmData, gzip, o5m, Encoding
try:
	from cStringIO import StringIO as BytesIO
except:
	from io import BytesIO 

if __name__=="__main__":

	if 1:
		fi = gzip.open("../coastout.o5m.gz", "rb")

		dec = o5m.O5mDecode(fi)
		dec.DecodeHeader()

		eof = False
		while not eof:
			eof = dec.DecodeNext()

	while 1:
		assert (Encoding.DecodeVarint(BytesIO(b'\x05')) == 5)
		assert (Encoding.DecodeVarint(BytesIO(b'\x7f')) == 127)
		assert (Encoding.DecodeVarint(BytesIO(b'\xc3\x02')) == 323)
		assert (Encoding.DecodeVarint(BytesIO(b'\x80\x80\x01')) == 16384)
		assert (Encoding.DecodeZigzag(BytesIO(b'\x08')) == 4)
		assert (Encoding.DecodeZigzag(BytesIO(b'\x80\x01')) == 64)
		assert (Encoding.DecodeZigzag(BytesIO(b'\x03')) == -2)
		assert (Encoding.DecodeZigzag(BytesIO(b'\x05')) == -3)
		assert (Encoding.DecodeZigzag(BytesIO(b'\x81\x01')) == -65)

		assert (Encoding.EncodeVarint(5) == b'\x05')
		assert (Encoding.EncodeVarint(127) == b'\x7f')
		assert (Encoding.EncodeVarint(323) == b'\xc3\x02')
		assert (Encoding.EncodeVarint(16384) == b'\x80\x80\x01')
		assert (Encoding.EncodeZigzag(4) == b'\x08')
		assert (Encoding.EncodeZigzag(64) == b'\x80\x01')
		assert (Encoding.EncodeZigzag(-2) == b'\x03')
		assert (Encoding.EncodeZigzag(-3) == b'\x05')
		assert (Encoding.EncodeZigzag(-65) == b'\x81\x01')

