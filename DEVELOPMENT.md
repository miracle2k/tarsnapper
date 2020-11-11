Make a release:

- Update tarsnapper/__init__.py
- git commit
- git tag -a 0.x
- git push && git push --tags && ./setup.py sdist upload
