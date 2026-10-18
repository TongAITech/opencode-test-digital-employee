from rc7_release import optional_enhancements, optional_plugin_payload


def test_optional_plugins_are_real_installable_packages_and_error_handling_is_skill() -> None:
    specs = dict(optional_plugin_payload.OPTIONAL_PLUGIN_SPECS)
    assert set(specs) == {
        "@perrylink/dsh-plugin-doctor",
        "dsh-vision-router",
        "dsh-plugin-anydoc",
        "dsh-memento",
    }
    assert specs["dsh-plugin-anydoc"] == "github:beancookie/dsh-plugin-anydoc#3af159ed06f62f3d2c61ab21c6a2475c71efbfa4"
    assert "dsh-error-handling" not in specs
    assert "dsh-error-handling" in optional_enhancements.BUILTIN_DSH_SKILLS
    assert dict(optional_enhancements.OPTIONAL_PLUGINS).keys() == specs.keys()
