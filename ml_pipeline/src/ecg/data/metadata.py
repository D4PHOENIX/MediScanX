"""
Metadata processing for the PTB-XL ECG dataset.
Maps raw diagnostic codes into the five target ECG superclasses.
"""

from __future__ import annotations

import ast
import os

import pandas as pd
from sklearn.preprocessing import MultiLabelBinarizer

from src.ecg.config import ECGTrainingConfig


class PTBXLMetadataProcessor:
    """Loads PTB-XL metadata and maps SCP codes into ECG superclasses."""

    @staticmethod
    def load_and_process(cfg: ECGTrainingConfig) -> tuple[pd.DataFrame, list[str]]:
        """Create a label dataframe containing the five target ECG superclasses."""

        database_path = os.path.join(cfg.data_dir, "ptbxl_database.csv")
        mapping_path = os.path.join(cfg.data_dir, "scp_statements.csv")

        labels_df = pd.read_csv(database_path, index_col="ecg_id")
        labels_df["scp_codes"] = labels_df["scp_codes"].apply(ast.literal_eval)

        mapping_df = pd.read_csv(mapping_path, index_col=0)
        mapping_df = mapping_df[mapping_df["diagnostic"] == 1]

        def aggregate_superclasses(code_map: dict[str, float]) -> list[str]:
            diagnoses: list[str] = []
            for code in code_map.keys():
                if code in mapping_df.index:
                    diagnoses.append(str(mapping_df.loc[code, "diagnostic_class"]))
            return sorted(set(diagnoses))

        labels_df["diagnostic_superclass"] = labels_df["scp_codes"].apply(aggregate_superclasses)

        mlb = MultiLabelBinarizer()
        encoded = pd.DataFrame(
            mlb.fit_transform(labels_df["diagnostic_superclass"]),
            columns=mlb.classes_,
            index=labels_df.index,
        )

        final_df = encoded[cfg.target_classes].copy()
        final_df["filename"] = labels_df["filename_lr"]
        return final_df, cfg.target_classes
