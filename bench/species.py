import re


def assign_species(protein_header: str, exclude_regex: str,
                   suffix_map: dict[str, str]) -> str | None:
    """Assign a protein to a species group.

    1. If `exclude_regex` matches the header, return None (e.g. contaminants).
    2. Otherwise return the species for the first matching suffix.
    3. An empty-string suffix key acts as a catch-all, applied only when no non-empty suffix matches (order-independent).
    """
    if exclude_regex and re.search(exclude_regex, protein_header):
        return None
    catch_all = None
    for suffix, species in suffix_map.items():
        if suffix == "":
            catch_all = species  # remember catch-all, apply only after no suffix matches
            continue
        if protein_header.endswith(suffix):
            return species
    return catch_all
