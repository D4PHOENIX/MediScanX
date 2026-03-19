"""
Shared MLOps telemetry and experiment lifecycle management.
Centralizes authentication and hyperparameter logging via Weights & Biases for all modalities.
"""
import os
import wandb
from typing import Any
from dotenv import load_dotenv
from dataclasses import asdict

class ExperimentTracker:
    """
    Manages MLOps telemetry, authentication and experiment lifecycle via Weights & Biases.
    """
    
    @staticmethod
    def initialize(cfg: Any) -> None:
        """Authenticates the environment using Kaggle Secrets and initializes WandB.

        Args:
            cfg (Any): The centralized config object to log as hyperparameters.
        """
        # Load environment variables from a local .env file (if it exists)
        load_dotenv()
        
        # WandB automatically looks for WANDB_API_KEY in the environment.
        if os.getenv("WANDB_API_KEY"):
            wandb.login()
            print("Successfully authenticated with Weights & Biases via Environment Variables!")
        else:
            print("WARNING: 'WANDB_API_KEY' not found in environment.")
            print("WandB will attempt to prompt for a key or run in offline/anonymous mode.")
            
        # Initialize the tracking session
        wandb.init(
            project=cfg.project_name,
            name=cfg.run_name,
            config=asdict(cfg)
        )
        
    @staticmethod
    def close() -> None:
        """Safely terminates the active WandB session to sync final logs."""
        wandb.finish()