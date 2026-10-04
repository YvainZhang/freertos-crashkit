CC ?= cc
AR ?= ar
PYTHON ?= python3
CFLAGS ?= -std=c11 -O2 -g -Wall -Wextra -Werror -pedantic
.PHONY: all test sanitize demo verify package rv32-build qemu-test
all: build/libcrashkit.a
build:
	mkdir -p build
build/crashkit.o: src/crashkit.c include/crashkit.h | build
	$(CC) $(CFLAGS) -Iinclude -c src/crashkit.c -o $@
build/libcrashkit.a: build/crashkit.o
	$(AR) rcs $@ $<
build/host-demo: examples/host-demo.c build/libcrashkit.a
	$(CC) $(CFLAGS) -Iinclude $< build/libcrashkit.a -o $@
demo: build/host-demo
	./build/host-demo build/demo.bin
	$(PYTHON) tools/analyze.py build/demo.bin --json build/demo.json --html build/demo.html
build/test-core: src/crashkit.c include/crashkit.h tests/test_core.c | build
	$(CC) $(CFLAGS) -Iinclude src/crashkit.c tests/test_core.c -o $@
test: build/test-core
	./build/test-core
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v
sanitize: | build
	$(CC) $(CFLAGS) -fsanitize=address,undefined -fno-omit-frame-pointer -Iinclude src/crashkit.c tests/test_core.c -o build/test-core-sanitize
	./build/test-core-sanitize
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v
verify: all test demo
	$(PYTHON) scripts/check-docs.py
package: verify
	$(PYTHON) scripts/release.py
rv32-build:
	$(PYTHON) scripts/build-rv32.py
qemu-test:
	$(PYTHON) scripts/test-qemu.py
