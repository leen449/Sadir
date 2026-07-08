import os
from dotenv import load_dotenv


load_dotenv()


class Settings:
    # Support both names to avoid breaking an existing .env.
    AZURE_OPENAI_API_KEY = (
        os.getenv("AZURE_OPENAI_API_KEY")
        or os.getenv("AZURE_OPENAI_KEY")
    )
    # Backward-compatible alias used by the current service/tests.
    AZURE_OPENAI_KEY = AZURE_OPENAI_API_KEY
    AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")


settings = Settings()
