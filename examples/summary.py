"""Counts what a file holds and lists its most used tags, without loading it all:

	python3 examples/summary.py tests/data/o5mtest.o5m
"""
import collections, sys
import pyo5m

class Summary(pyo5m.Handler):
	def __init__(self):
		self.counts = collections.Counter()
		self.tags = collections.Counter()

	def store_attributes(self, attributes):
		print("attributes", attributes)

	def store_bounds(self, bounds):
		print("bounds", bounds)

	def store_node(self, node):
		self.counts["nodes"] += 1
		self.tags.update(node.tags.keys())

	def store_way(self, way):
		self.counts["ways"] += 1
		self.tags.update(way.tags.keys())

	def store_relation(self, relation):
		self.counts["relations"] += 1
		self.tags.update(relation.tags.keys())

if __name__ == "__main__":
	path = sys.argv[1]
	summary = Summary()
	with pyo5m.open_file(path) as source:
		pyo5m.decoder(source, summary, pyo5m.format_of(path)[0]).run()
	print(dict(summary.counts))
	print("most used tags", summary.tags.most_common(5))
