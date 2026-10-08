.PHONY: all clean

SOURCE := src/claims-terminal.cbl
SQL_INCLUDES := src/copybooks/transaction-begin \
	src/copybooks/request-identity \
	src/copybooks/deductible-math \
	src/copybooks/clawback-order \
	src/copybooks/audit-reserve
PRECOMPILED := build/claims-terminal.cob
TARGET := bin/claims-terminal

all: $(TARGET)

$(PRECOMPILED): $(SOURCE) $(SQL_INCLUDES) \
	src/copybooks/validation-rules.cpy
	mkdir -p build
	ocesql --inc=src/copybooks $(SOURCE) $(PRECOMPILED)

$(TARGET): $(PRECOMPILED)
	cobc -x -fixed -Wall -I src/copybooks -o $(TARGET) \
		$(PRECOMPILED) \
		-Q "-Wl,--no-as-needed" -locesql -lpq

clean:
	rm -f $(PRECOMPILED) $(TARGET)
