import pandas as pd


def prepare_screener_table(df: pd.DataFrame, feature_ai_enabled: bool) -> pd.DataFrame:
    """Prepare screener output columns for display."""
    table_df = df.copy()
    rename_map = {"Score": "Conviction Score", "Quality_Gate_Failures": "Gate Failures"}
    if feature_ai_enabled and "ai_score" in table_df.columns:
        rename_map["ai_score"] = "AI Score"
    table_df = table_df.rename(columns=rename_map)
    if (
        feature_ai_enabled
        and "AI Score" in table_df.columns
        and "Conviction Score" in table_df.columns
    ):
        cols = list(table_df.columns)
        ai_col = cols.pop(cols.index("AI Score"))
        conv_idx = cols.index("Conviction Score")
        cols.insert(conv_idx + 1, ai_col)
        table_df = table_df[cols]
    return table_df
