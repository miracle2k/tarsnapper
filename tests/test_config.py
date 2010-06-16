from tarsnapper.config import load_config, ConfigError
from nose.tools import assert_raises


def test_empty_config():
    assert_raises(ConfigError, load_config, """
    deltas: 1d 2d
    jobs:
    """)
    assert_raises(ConfigError, load_config, """
    deltas: 1d 2d
    """)


def test_no_sources():
    assert_raises(ConfigError, load_config, """
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
    """)['foo']['target'] == '$name-$date'


def test_no_deltas():
    assert_raises(ConfigError, load_config, """
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
    """)['foo']['deltas']) == 3


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
    r = load_config("""
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
    assert r['foo']['dateformat'] == 'ABC'
    assert r['bar']['dateformat'] == '123'


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
    """)['foo']['sources'] == ['/etc']


def test_source_and_sources():
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