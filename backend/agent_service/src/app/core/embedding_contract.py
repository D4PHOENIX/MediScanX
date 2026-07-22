import typing

"""
Single source of truth for the RAG embedding stack.
NOTE: The corpus is embedded OFFLINE with ncbi/MedCPT-Article-Encoder in a 
separate seeder. This file is the single swap-point if the model family changes.
"""

QUERY_ENCODER_MODEL: typing.Final[str] = "ncbi/MedCPT-Query-Encoder"
CROSS_ENCODER_MODEL: typing.Final[str] = "ncbi/MedCPT-Cross-Encoder"

# EMBEDDING_DIM must exactly match the halfvec(N) dimension in schema/0006_medcpt_768.sql
# Do not make this env-configurable as the DB schema depends on this fixed size.
EMBEDDING_DIM: typing.Final[int] = 768
NORMALIZE: typing.Final[bool] = True
MAX_LENGTH: typing.Final[int] = 512
