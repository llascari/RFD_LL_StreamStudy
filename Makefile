.PHONY: run test gui-test fixtures compile clean

run:
	python3 -m streamstudy

test:
	python3 -m unittest discover -s tests -t . -v

gui-test:
	xvfb-run -a python3 -m unittest discover -s tests -t . -v

fixtures:
	python3 scripts/capture_fixtures.py

compile:
	python3 -m compileall -q streamstudy tests scripts

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf build dist *.egg-info
