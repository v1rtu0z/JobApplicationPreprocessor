"""Helpers for rendering individual job rows in the Jobs view."""


def get_row_value(row, col_name: str, column_index_map: dict, default: str = "") -> str:
    """Get value from itertuples row using column index map.
    itertuples(index=False) returns tuples where columns are in order.
    """
    if col_name not in column_index_map:
        return default
    col_idx = column_index_map[col_name]
    try:
        value = row[col_idx]
        return str(value) if value is not None else default
    except (IndexError, AttributeError, TypeError):
        return default
