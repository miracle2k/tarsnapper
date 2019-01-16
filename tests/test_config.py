from nose.tools import assert_raises

from tarsnapper.config import load_config, ConfigError


def test_empty_config():
    assert_raises(ConfigError, load_config, """
    deltas: 1d 2d
    jobs:
    """)
    assert_raises(ConfigError, load_config, """
    deltas: 1d 2d
    """)


def test_aliases():
    """Loading of the "alias" option."""
    assert load_config("""
    jobs:
      foo:
        target: foo-$date
        alias: foo
    """)[0]['foo'].aliases == ['foo']
    assert load_config("""
    jobs:
      foo:
        target: foo-$date
        aliases:
          - foo
    """)[0]['foo'].aliases == ['foo']


def test_excludes():
    """Loading of the "excludes" option."""
    assert load_config("""
    jobs:
      foo:
        target: foo-$date
        exclude: foo
    """)[0]['foo'].excludes == ['foo']
    assert load_config("""
    jobs:
      foo:
        target: foo-$date
        excludes:
          - foo
    """)[0]['foo'].excludes == ['foo']


def test_no_sources():
    # It's ok to load a backup job file without sources
    load_config("""
    jobs:
      foo:
        deltas: 1d 2d 3d
        target:  $date
    """)


def test_no_target():
    assert_raises(ConfigError, load_config, """
    jobs:
      foo:
        deltas: 1d 2d 3d
        sources: /etc
    """)


def test_global_target():
    assert load_config("""
    target: $name-$date
    jobs:
      foo:
        deltas: 1d 2d 3d
        sources: sdf
    """)[0]['foo'].target == '$name-$date'


def test_empty_job():
    """An empty job may be valid in some cases."""
    assert load_config("""
    target: $name-$date
    jobs:
      foo:
    """)[0]['foo']


def test_no_deltas():
    # It's ok to load a job without deltas
    load_config("""
    jobs:
      foo:
        sources: /etc
        target:  $date
    """)


def test_global_deltas():
    assert len(load_config("""
    deltas: 1d 2d 3d
    jobs:
      foo:
        sources: /etc
        target: $date
    """)[0]['foo'].deltas) == 3


def test_target_has_name():
    assert_raises(ConfigError, load_config, """
    target: $date
    jobs:
      foo:
        sources: /etc
        deltas: 1d 2d
    """)

    # A job-specific target does not need a name placeholder
    load_config("""
    jobs:
      foo:
        sources: /etc
        deltas: 1d 2d
        target: $date
    """)


def test_target_has_date():
    assert_raises(ConfigError, load_config, """
    target: $name
    jobs:
      foo:
        sources: /etc
        deltas: 1d 2d
    """)
    assert_raises(ConfigError, load_config, """
    jobs:
      foo:
        target: $name
        sources: /etc
        deltas: 1d 2d
    """)


def test_dateformat_inheritance():
    r, _ = load_config("""
    dateformat: ABC
    target: $name-$date
    deltas: 1d 2d
    jobs:
      foo:
        sources: /etc
      bar:
        sources: /usr
        dateformat: "123"
    """)
    assert r['foo'].dateformat == 'ABC'
    assert r['bar'].dateformat == '123'


def test_unsupported_keys():
    assert_raises(ConfigError, load_config, """
    jobs:
      foo:
        target: $date
        sources: /etc
        deltas: 1d 2d
        UNSUPPORTED: 123
    """)


def test_single_source():
    assert load_config("""
    target: $name-$date
    deltas: 1d 2d
    jobs:
      foo:
        source: /etc
    """)[0]['foo'].sources == ['/etc']


def test_source_and_sources():
    """You can't use both options at the same time."""
    assert_raises(ConfigError, load_config, """
    target: $name-$date
    deltas: 1d 2d
    jobs:
      foo:
        source: /etc
        sources:
          /usr
          /var
    """)


def test_alias_and_aliases():
    """You can't use both options at the same time."""
    assert_raises(ConfigError, load_config, """
    target: $name-$date
    deltas: 1d 2d
    jobs:
      foo:
        alias: doo
        aliases:
          loo
          moo
    """)


def test_exclude_and_excludes():
    """You can't use both options at the same time."""
    assert_raises(ConfigError, load_config, """
    target: $name-$date
    deltas: 1d 2d
    jobs:
      foo:
        exclude: doo
        excludes:
          loo
          moo
    """)


def test_named_delta():
    c = load_config("""
    target: $name-$date
    deltas: 1d 10d
    delta-names:
      myDelta: 1d 7d 30d
      otherDelta: 1d 7d 30d 90d
    jobs:
      foo:
        source: /foo/
        delta: myDelta
      bar:
        source: /foo/
        delta: otherDelta
      baz:
        source: /foo/
    """)
    assert len(c[0]['baz'].deltas) == 2
    assert len(c[0]['foo'].deltas) == 3
    assert len(c[0]['bar'].deltas) == 4


def test_unspecified_named_delta():
    assert_raises(ConfigError, load_config, """
    target: $name-$date
    delta-names:
      myDelta:
    jobs:
      foo:
        source: /foo/
        delta: myDelta
    """)


def test_undefined_named_delta():
    assert_raises(ConfigError, load_config, """
    target: $name-$date
    delta-names:
      myDelta: 1d 7d 30d
    jobs:
      foo:
        source: /foo/
        delta: importantDelta
    """)


def test_named_delta_and_deltas():
    """You can't use both named delta and deltas at the same time."""
    assert_raises(ConfigError, load_config, """
    target: $name-$date
    delta-names:
      myDelta: 1d 7d 30d
    jobs:
      foo:
        source: /foo/
        delta: myDelta
        deltas: 5d 10d
    """)
