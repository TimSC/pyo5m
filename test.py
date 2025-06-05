import OsmData, gzip, o5m, pyo5mEncoding
from io import BytesIO 

if __name__=="__main__":

	if 1:
		fi = gzip.open("o5mtest.o5m.gz", "rb")

		dec = o5m.O5mDecode(fi)
		dec.DecodeHeader()

		eof = False
		while not eof:
			eof = dec.DecodeNext()

	if 1:
		assert (pyo5mEncoding.DecodeVarint(BytesIO(b'\x05')) == 5)
		assert (pyo5mEncoding.DecodeVarint(BytesIO(b'\x7f')) == 127)
		assert (pyo5mEncoding.DecodeVarint(BytesIO(b'\xc3\x02')) == 323)
		assert (pyo5mEncoding.DecodeVarint(BytesIO(b'\x80\x80\x01')) == 16384)
		assert (pyo5mEncoding.DecodeZigzag(BytesIO(b'\x08')) == 4)
		assert (pyo5mEncoding.DecodeZigzag(BytesIO(b'\x80\x01')) == 64)
		assert (pyo5mEncoding.DecodeZigzag(BytesIO(b'\x03')) == -2)
		assert (pyo5mEncoding.DecodeZigzag(BytesIO(b'\x05')) == -3)
		assert (pyo5mEncoding.DecodeZigzag(BytesIO(b'\x81\x01')) == -65)

		assert (pyo5mEncoding.EncodeVarint(5) == b'\x05')
		assert (pyo5mEncoding.EncodeVarint(127) == b'\x7f')
		assert (pyo5mEncoding.EncodeVarint(323) == b'\xc3\x02')
		assert (pyo5mEncoding.EncodeVarint(16384) == b'\x80\x80\x01')
		assert (pyo5mEncoding.EncodeZigzag(4) == b'\x08')
		assert (pyo5mEncoding.EncodeZigzag(64) == b'\x80\x01')
		assert (pyo5mEncoding.EncodeZigzag(-2) == b'\x03')
		assert (pyo5mEncoding.EncodeZigzag(-3) == b'\x05')
		assert (pyo5mEncoding.EncodeZigzag(-65) == b'\x81\x01')

