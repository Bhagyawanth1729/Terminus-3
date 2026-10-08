COBC ?= cobc
COBFLAGS ?= -x -free -Wall -Wextra
TARGET := build/depot-ledger-bin
SOURCE := src/core.cob
FRAGMENTS := a1/a.c b2/b.c c3/c.c d4/d.c

.PHONY: all clean sample

all: $(TARGET)

$(TARGET): $(SOURCE) copybooks/rows.cpy $(FRAGMENTS)
	mkdir -p build
	$(COBC) $(COBFLAGS) -I copybooks -I a1 -I b2 -I c3 -I d4 -o $(TARGET) $(SOURCE)

clean:
	rm -rf build

sample: all
	rm -rf sample/output
	bin/depot-ledger --parts sample/parts.dat --stock sample/opening.dat --events sample/events.dat --output sample/output
	for report in closing-stock.dat open-transit.dat exceptions.dat summary.dat; do echo "== $$report =="; cat "sample/output/$$report"; done
