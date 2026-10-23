"""Read attribute rows from an Esri File Geodatabase (.gdb) using only the standard library.

Reads straight from a .zip, so nothing needs extracting. Follows the public
OpenFileGDB format notes (github.com/rouault/dump_gdbtable/wiki/FGDB-Spec).
Geometry is returned as raw bytes (or skipped); only attributes are decoded.

    python -m stormdata.filegdb Hurricane_Harvey_Flow.zip            # list tables and fields
    python -m stormdata.filegdb Hurricane_Harvey_Flow.zip TABLE out.csv
"""
import csv
import struct
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import PurePosixPath

INT16, INT32, FLOAT32, FLOAT64, STRING, DATETIME, OBJECTID, GEOMETRY, BINARY, RASTER, GUID, GLOBALID, XML = range(13)
TYPE_NAMES = ['int16', 'int32', 'float32', 'float64', 'string', 'datetime', 'objectid',
              'geometry', 'binary', 'raster', 'guid', 'globalid', 'xml']
EXCEL_EPOCH = datetime(1899, 12, 30)


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, n):
        if self.pos + n > len(self.data):
            raise ValueError('Unexpected end of geodatabase table')
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def unpack(self, fmt):
        return struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))[0]

    def varuint(self):
        shift = value = 0
        while True:
            b = self.take(1)[0]
            value |= (b & 0x7F) << shift
            if not b & 0x80:
                return value
            shift += 7

    def utf16(self, chars):
        return self.take(chars * 2).decode('utf-16-le')


class Field:
    def __init__(self, name, alias, ftype, nullable, extra=None):
        self.name, self.alias, self.type, self.nullable, self.extra = name, alias, ftype, nullable, extra or {}

    def __repr__(self):
        return f'{self.name}:{TYPE_NAMES[self.type]}{"?" if self.nullable else ""}'


def _read_geometry_field(r):
    r.take(1)  # unknown
    flag = r.take(1)[0]
    wkt = r.utf16(r.unpack('H') // 2)
    gflags = r.take(1)[0]
    has_m, has_z = bool(gflags & 2), bool(gflags & 4)
    xorigin, yorigin, xyscale = struct.unpack('<3d', r.take(24))
    r.take(8 * 2 * (has_m + has_z))     # m and z origin/scale
    r.take(8 * (1 + has_m + has_z))     # tolerances
    xmin, ymin, xmax, ymax = struct.unpack('<4d', r.take(32))
    # Optional z/m extents come before the spatial-grid block; skip them until
    # the grid marker (a zero byte, then a count of 1-3 grid sizes) appears.
    for _ in range(3):
        if r.data[r.pos] == 0 and 1 <= struct.unpack_from('<I', r.data, r.pos + 1)[0] <= 3:
            break
        r.take(16)
    r.take(1)
    r.take(8 * r.unpack('I'))
    return flag, dict(wkt=wkt, has_z=has_z, has_m=has_m, extent=(xmin, ymin, xmax, ymax),
                      xorigin=xorigin, yorigin=yorigin, xyscale=xyscale)


def _varint(r):
    """Signed varint used for coordinate deltas: bit 6 of the first byte is the sign."""
    b = r.take(1)[0]
    value, shift, negative = b & 0x3F, 6, b & 0x40
    while b & 0x80:
        b = r.take(1)[0]
        value |= (b & 0x7F) << shift
        shift += 7
    return -value if negative else value


POINT_TYPES = {1, 9, 11, 21, 52}
POLY_TYPES = {3, 5, 10, 13, 15, 19, 23, 25, 50, 51}


def decode_shape(blob, geom):
    """Return x/y coordinates in the layer's own coordinate system.

    A point gives (x, y). A polyline or polygon gives a list of parts, each a list
    of (x, y). Z and M values, if any, follow the x/y block and are not read.
    """
    if not blob:
        return None
    r = Reader(blob)
    code = r.varuint()
    base = code & 0xFF
    ox, oy, scale = geom['xorigin'], geom['yorigin'], geom['xyscale']
    if base in POINT_TYPES:
        return (r.varuint() - 1) / scale + ox, (r.varuint() - 1) / scale + oy
    if base not in POLY_TYPES:
        raise ValueError(f'Unsupported geometry type {code}')
    npoints = r.varuint()
    if not npoints:
        return []
    nparts = r.varuint()
    if base in (50, 51) and code & 0x20000000:
        r.varuint()  # curve count; curve segments are stored after the vertices
    for _ in range(4):
        r.varuint()  # bounding box
    sizes = [r.varuint() for _ in range(nparts - 1)]
    sizes.append(npoints - sum(sizes))
    x = y = 0
    parts = []
    for size in sizes:
        part = []
        for _ in range(size):
            x += _varint(r)
            y += _varint(r)
            part.append((x / scale + ox, y / scale + oy))
        parts.append(part)
    return parts


def parse_fields(r):
    r.pos = 32
    r.pos = r.unpack('Q')
    r.unpack('I')  # header size
    version = r.unpack('I')
    if version not in (3, 4):
        raise ValueError(f'Unsupported field section version {version}')
    r.unpack('I')  # layer flags
    fields = []
    for _ in range(r.unpack('H')):
        name = r.utf16(r.take(1)[0])
        alias = r.utf16(r.take(1)[0])
        ftype = r.take(1)[0]
        extra = {}
        if ftype in (INT16, INT32, FLOAT32, FLOAT64, DATETIME):
            r.take(1)
            flag = r.take(1)[0]
            r.take(r.take(1)[0])  # default value
        elif ftype == STRING:
            extra['width'] = r.unpack('I')
            flag = r.take(1)[0]
            r.take(r.varuint())
        elif ftype == OBJECTID:
            r.take(1)
            flag = r.take(1)[0]
        elif ftype == GEOMETRY:
            flag, extra = _read_geometry_field(r)
        elif ftype in (BINARY, GUID, GLOBALID, XML):
            r.take(1)
            flag = r.take(1)[0]
        else:
            raise ValueError(f'Unsupported field type {ftype} for {name!r}')
        fields.append(Field(name, alias, ftype, bool(flag & 1), extra))
    return fields


def row_offsets(tablx):
    r = Reader(tablx)
    r.unpack('I')
    blocks = r.unpack('I')
    total = r.unpack('I')
    size = r.unpack('I')
    if blocks and blocks * 1024 < total:
        raise ValueError('Sparse geodatabase index is not supported')
    for oid in range(1, total + 1):
        off = int.from_bytes(r.take(size), 'little')
        if off:
            yield oid, off


def read_rows(table, tablx, keep_geometry=False):
    """Yield (fields, dict) rows. The OBJECTID comes from the index position."""
    r = Reader(table)
    fields = parse_fields(r)
    nullable = [f for f in fields if f.nullable and f.type != OBJECTID]
    null_bytes = (len(nullable) + 7) // 8
    for oid, off in row_offsets(tablx):
        r.pos = off
        r.unpack('I')  # row size
        nulls = r.take(null_bytes)
        row, bit = {}, 0
        for f in fields:
            if f.type == OBJECTID:
                row[f.name] = oid
                continue
            if f.nullable:
                is_null = nulls[bit // 8] >> (bit % 8) & 1
                bit += 1
                if is_null:
                    row[f.name] = None
                    continue
            if f.type == INT16:
                v = r.unpack('h')
            elif f.type == INT32:
                v = r.unpack('i')
            elif f.type == FLOAT32:
                v = r.unpack('f')
            elif f.type == FLOAT64:
                v = r.unpack('d')
            elif f.type == DATETIME:
                v = EXCEL_EPOCH + timedelta(days=r.unpack('d'))
            elif f.type in (STRING, XML):
                v = r.take(r.varuint()).decode('utf-8')
            elif f.type in (GEOMETRY, BINARY):
                v = r.take(r.varuint())
                if f.type == GEOMETRY and not keep_geometry:
                    v = None
            elif f.type in (GUID, GLOBALID):
                v = r.take(16).hex()
            else:
                raise ValueError(f'Unsupported field type {f.type}')
            row[f.name] = v
        yield fields, row


class GeoDatabase:
    """A .gdb folder inside a zip archive."""
    def __init__(self, zip_path):
        self.zip = zipfile.ZipFile(zip_path)
        gdbs = sorted({str(PurePosixPath(n).parent) for n in self.zip.namelist() if n.endswith('.gdbtable')})
        if len(gdbs) != 1:
            raise ValueError(f'Expected one .gdb in {zip_path}, found {gdbs}')
        self.prefix = gdbs[0]
        self.tables = {row['Name']: row['ID'] for _, row in self._rows(1)}

    def _file(self, number, ext):
        return self.zip.read(f'{self.prefix}/a{number:08x}.{ext}')

    def _rows(self, number, keep_geometry=False):
        return read_rows(self._file(number, 'gdbtable'), self._file(number, 'gdbtablx'), keep_geometry)

    def user_tables(self):
        return [n for n in self.tables if not n.startswith('GDB_')]

    def fields(self, name):
        return parse_fields(Reader(self._file(self.tables[name], 'gdbtable')))

    def rows(self, name, keep_geometry=False):
        return [row for _, row in self._rows(self.tables[name], keep_geometry)]


def main(argv):
    db = GeoDatabase(argv[0])
    if len(argv) == 1:
        for name in db.user_tables():
            print(f'{name}: {len(db.rows(name))} rows')
            print('   ', db.fields(name))
        return
    rows = db.rows(argv[1])
    names = [f.name for f in db.fields(argv[1]) if f.type != GEOMETRY]
    with open(argv[2], 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=names, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    print(f'Wrote {len(rows)} rows to {argv[2]}')


if __name__ == '__main__':
    main(sys.argv[1:])
