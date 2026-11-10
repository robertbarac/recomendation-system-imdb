import os
import time
from getpass import getpass
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm
from dotenv import load_dotenv


FALLBACK_POSTER = (
    "https://image.tmdb.org/t/p/original/"
    "uXDfjJbdP4ijW5hWSBrPrlKpxab.jpg"
)
PROGRESS_FILE = Path("data/movies_progress.csv")
OUTPUT_FILE = Path("data/movies_final.csv")
CHECKPOINT_INTERVAL = 100
MAX_ATTEMPTS = 4


def add_url(row):
    return f"https://www.imdb.com/title/tt{row}/"


def calculate_rating(df):
    ratings = pd.read_csv("data/ratings.csv")
    print(ratings.info())
    ratings["movieId"] = ratings["movieId"].astype(str)
    agg_df = ratings.groupby("movieId").agg(
        rating_count=("rating", "count"),
        rating_mean=("rating", "mean"),
    ).reset_index()
    return df.merge(agg_df, on="movieId")


def fetch_poster(session, tmdb_id, api_key):
    if pd.isna(tmdb_id) or not str(tmdb_id).strip():
        return FALLBACK_POSTER, True, None

    tmdb_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = session.get(
                tmdb_url,
                params={"api_key": api_key},
                timeout=(5, 20),
            )
        except (requests.ConnectionError, requests.Timeout) as error:
            if attempt == MAX_ATTEMPTS - 1:
                return None, False, str(error)
            time.sleep(2**attempt)
            continue

        if response.status_code == 404:
            return FALLBACK_POSTER, True, None
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == MAX_ATTEMPTS - 1:
                return None, False, f"TMDB returned HTTP {response.status_code}"
            time.sleep(2**attempt)
            continue

        response.raise_for_status()
        poster_path = response.json().get("poster_path")
        poster = (
            f"https://image.tmdb.org/t/p/w500{poster_path}"
            if poster_path
            else FALLBACK_POSTER
        )
        return poster, True, None

    return None, False, "TMDB request failed after all attempts"


def save_progress(df):
    temporary_file = PROGRESS_FILE.with_suffix(".csv.tmp")
    df.to_csv(temporary_file, index=False)
    temporary_file.replace(PROGRESS_FILE)


def add_poster(df, api_key):
    df = df.copy()
    df["movieId"] = df["movieId"].astype(str)

    if PROGRESS_FILE.exists():
        progress_df = pd.read_csv(PROGRESS_FILE, dtype={"movieId": str})
        if not progress_df["movieId"].equals(df["movieId"]):
            raise ValueError(
                f"{PROGRESS_FILE} does not match the current movie list; "
                "move it aside before starting a new dataset."
            )
        if not {"poster_path", "_poster_status"}.issubset(progress_df.columns):
            raise ValueError(f"{PROGRESS_FILE} is missing required progress columns.")
        df["poster_path"] = progress_df["poster_path"]
        df["_poster_status"] = progress_df["_poster_status"]
    else:
        df["poster_path"] = None
        df["_poster_status"] = "pending"

    processed_since_checkpoint = 0
    with requests.Session() as session:
        try:
            for i, row in tqdm(df.iterrows(), total=df.shape[0]):
                if row["_poster_status"] == "done":
                    continue

                poster, completed, error = fetch_poster(
                    session, row["tmdbId"], api_key
                )
                df.at[i, "poster_path"] = poster
                df.at[i, "_poster_status"] = "done" if completed else "pending"
                processed_since_checkpoint += 1
                time.sleep(0.1)

                if error:
                    print(
                        f"\nNo se pudo consultar TMDB para movieId={row['movieId']}: "
                        f"{error}. Se reintentará al ejecutar el script otra vez."
                    )

                if processed_since_checkpoint >= CHECKPOINT_INTERVAL:
                    save_progress(df)
                    processed_since_checkpoint = 0
        except Exception:
            save_progress(df)
            raise

    save_progress(df)
    return df


def main():
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    api_key = os.environ.get("TMDB_API_KEY")
    if not api_key:
        api_key = getpass("Ingresa tu clave de TMDB: ")
    if not api_key:
        raise RuntimeError("Se necesita una clave de TMDB para consultar los pósteres.")

    movies_df = pd.read_csv("data/movies.csv")
    links_df = pd.read_csv("data/links.csv", dtype=str)
    movies_df["movieId"] = movies_df["movieId"].astype(str)

    merged_df = movies_df.merge(links_df, on="movieId", how="left")
    merged_df["url"] = merged_df["imdbId"].apply(add_url)
    print(merged_df.iloc[1, :])

    result_df = calculate_rating(merged_df)
    result_df = add_poster(result_df, api_key)

    pending_count = result_df["_poster_status"].eq("pending").sum()
    if pending_count:
        print(
            f"\nQuedaron {pending_count} películas pendientes. "
            f"El progreso está guardado en {PROGRESS_FILE}; "
            "ejecuta el script otra vez para reintentarlas."
        )
        return 1

    result_df.drop(columns="_poster_status").to_csv(OUTPUT_FILE, index=False)
    print(f"\nArchivo generado: {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
