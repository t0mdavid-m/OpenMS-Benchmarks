from bench.species import assign_species

SUFFIX = {"_HUMAN": "HUMAN", "_YEAST": "YEAST", "_ECOLI": "ECOLI"}


def test_assigns_by_suffix():
    assert assign_species("sp|P49327|FAS_HUMAN", "Cont_", SUFFIX) == "HUMAN"
    assert assign_species("sp|P00330|ADH1_YEAST", "Cont_", SUFFIX) == "YEAST"


def test_contaminant_excluded_even_if_suffix_matches():
    # This is the documented trap: contaminant carries an _ECOLI suffix.
    assert assign_species("sp|Cont_P00722|BGAL_ECOLI", "Cont_", SUFFIX) is None


def test_unknown_suffix_returns_none():
    assert assign_species("sp|X|FOO_BAR", "Cont_", SUFFIX) is None


def test_single_group_placeholder_rule():
    # Placeholder datasets map everything non-contaminant to one group.
    assert assign_species("sp|X|FOO_BAR", "Cont_", {"": "ALL"}) == "ALL"
    assert assign_species("sp|Cont_X|FOO_BAR", "Cont_", {"": "ALL"}) is None
