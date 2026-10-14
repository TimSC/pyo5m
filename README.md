# pyo5m

Reads and writes OpenStreetMap data as o5m, o5c, OSM XML and osmChange XML, in pure Python with no dependencies. It is the Python counterpart of [cppo5m](https://github.com/TimSC/cppo5m), and follows the same design.

Install with:

    python3 -m pip install .

Version 2 reorganised the library and is not compatible with version 1.

## Whole files

```python
import pyo5m

data = pyo5m.load("area.o5m.gz")
print(len(data.nodes), len(data.ways), len(data.relations))
pyo5m.save(data, "area.osm")

change = pyo5m.load_change("diff.osc")
```

The format follows the file name: `.o5m`, `.o5c`, `.osm` or `.osc`, optionally followed by `.gz`. `save` writes to a temporary file beside the destination and moves it into place only when it is complete, so a failure leaves an existing file as it was.

## Streaming

Decoders send what they read to a `Handler`, one object at a time. The encoders are handlers, so a conversion never needs the whole file in memory:

```python
with pyo5m.open_file("area.o5m") as source, pyo5m.open_file("area.osm.gz", "wb") as target:
    pyo5m.O5mDecoder(source, pyo5m.OsmXmlEncoder(target)).run()
```

To do something else with the objects, subclass `Handler` and override the methods you need: `store_is_diff`, `store_attributes`, `store_bounds`, `store_node`, `store_way`, `store_relation`, `reset` and `finish`. `OsmData` is a handler that keeps everything, and `OsmData.stream_to(handler)` replays it into another. `run()` decodes the whole input; `decode_next()` decodes a piece at a time and returns False at the end. Either way the handler's `finish` is called once, at the end. An exception raised by a handler reaches the caller unchanged; invalid input raises `pyo5m.DecodeError`.

`pyo5m.decoder(source, handler, format)` and `pyo5m.encoder(target, format)` choose the class by format name. See `examples/` for a converter and a handler that summarises a file.

osmChange documents work the same way with a `ChangeHandler`, which receives each action element as an `OsmChangeBlock` (`action`, `if_unused` and an `OsmData` of its objects). `OsmChange` keeps them, and `OsmChangeXmlEncoder` writes them; within a delete it writes relations first, then ways, then nodes.

## Data model

| Class | Fields |
|---|---|
| `Node` | `id`, `lat`, `lon`, `tags`, `meta` |
| `Way` | `id`, `refs` (node IDs), `tags`, `meta` |
| `Relation` | `id`, `members` (`Member(type, ref, role)`), `tags`, `meta` |
| `MetaData` | `version`, `timestamp`, `changeset`, `uid`, `username`, `visible`, `extras` |
| `Bounds` | `min_lon`, `min_lat`, `max_lon`, `max_lat` |
| `OsmData` | `nodes`, `ways`, `relations`, `bounds`, `attributes`, `is_diff` |

They are dataclasses, so they compare by value. Timestamps are aware datetimes in UTC; a naive one given to an encoder is taken to be UTC. Any metadata may be `None`. `extras` holds an XML element's other attributes, as strings; o5m has nowhere to keep them.

`visible` is False for a deleted object. In o5c a delete is an object cut short after its ID and metadata: the decoder gives it no tags, members or position, and the encoder writes any object with `visible` False that way. OSM XML writes `visible="false"` and no position.

`OsmData.crop(bounds)` gives what a map query of an area does: the nodes inside it, the ways with one of those nodes and all their nodes, the relations with one of those as a member, and the relations containing those, at any depth. `OsmData.index()` gives the objects by type and ID.

## Document attributes

`OsmData.attributes` holds attributes of the document as a whole, such as the `edit_activity_id` and `atomic_edit_id` that pycrocosm records in its downloads. In XML they are attributes of the root element. o5m has no standard place for them, so they go in a dataset of cppo5m's own (type 0xc0) straight after the header, and pyo5m and cppo5m read each other's. Other programs skip it, as the format requires, though osmconvert drops it if it rewrites the file. Pass `attributes` to an encoder, or send them with `store_attributes` before any object.

## Compatibility

Node positions in o5m are delta coded in 32 bits, wrapping round, as osmconvert and cppo5m write them, so a way crossing the antimeridian is stored compactly and reads correctly elsewhere. o5m keeps positions to seven decimal places; coordinates beyond about ±214.7 degrees are refused. XML keeps every digit. Strings containing a zero byte are refused by the o5m encoder, since the format uses it to end strings.

## Tests

    python3 -m unittest discover tests

Some tests check files against osmconvert, and are skipped if it is not installed.
