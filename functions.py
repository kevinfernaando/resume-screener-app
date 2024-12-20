import pandas as pd
from openai import OpenAI
import re
import json
import os
import fitz
import numpy as np
from dotenv import load_dotenv

api_key = os.getenv("API_KEY")
client = OpenAI(api_key=api_key)


def extract_text_from_pdf(file_path):
    pdf = fitz.open(file_path)
    final_text = [pdf[page_number].get_text() for page_number in range(len(pdf))]
    return "\n".join(final_text)


def preprocess_resume(resume_text):
    """
    Preprocesses the resume text to extract and clean key details.

    Args:
        resume_text (str): Raw text of the resume.

    Returns:
        dict: A dictionary with the cleaned resume text, name, and email.
    """
    # Extract email
    email = re.search(r"[\w\.-]+@[\w\.-]+", resume_text)
    email = email.group(0) if email else "Email not found"

    # Simplify resume text (remove excess whitespace)
    cleaned_text = " ".join(resume_text.split())

    # Extract name (assume the name is in the first line or add custom logic)
    name = "Name not found"
    lines = resume_text.splitlines()
    if lines:
        name = lines[0].strip()

    return {"resume_text": cleaned_text, "name": name, "email": email}


def format_qualifications(qualifications):
    """
    Formats qualifications as bullet points for better readability.

    Args:
        qualifications (list): List of qualifications.

    Returns:
        str: Formatted string of qualifications.
    """
    return "\n".join(f"- {q}" for q in qualifications)


def check_requirements(
    resume_data, min_qualifications, pref_qualifications, added_value
):
    """
    Evaluates a resume against a list of requirements using OpenAI's API.

    Args:
        resume_data (dict): Preprocessed resume data with text, name, and email.
        min_qualifications (list): List of minimum qualifications.
        pref_qualifications (list): List of preferred qualifications.
        added_value (list): List of added-value qualifications.

    Returns:
        dict: A dictionary of results for each qualification or an error message.
    """
    prompt = f"""
You are an expert in evaluating resumes for job qualifications. Your task is to evaluate whether the candidate meets the qualifications listed below.

---
Resume:
{resume_data['resume_text']}
---
Minimum Qualifications:
{format_qualifications(min_qualifications)}
---
Preferred Qualifications:
{format_qualifications(pref_qualifications)}
---
Added Value:
{format_qualifications(added_value)}
---

Your response should strictly follow this JSON format:
{{
    "name": "Find the candidate name",
    "email": "{resume_data['email']}",
    "summarization": "A concise summary of the resume (2-3 sentences).",
    "is_veteran": "Detect is the candidate a veteran or not based on the resume, respond with True or False only",
    "qualifications": [
        {{
            "qualification_type": "Minimum Qualification",
            "qualification": "Exact qualification text from the input",
            "true_or_false": true/false,
            "explanation": "Why the candidate meets/does not meet this qualification, based on the resume content."
        }},
        {{
            "qualification_type": "Preferred Qualification",
            "qualification": "Exact qualification text from the input",
            "true_or_false": true/false,
            "explanation": "Why the candidate meets/does not meet this qualification, based on the resume content."
        }},
        {{
            "qualification_type": "Added Value",
            "qualification": "Exact qualification text from the input",
            "true_or_false": true/false,
            "explanation": "Why the candidate meets/does not meet this qualification, based on the resume content."
        }}
    ]
}}
- Include all qualifications from the input in your response.
- If any information is missing from the resume, state this in the explanation.
- Maintain a formal and professional tone.
- Analyze and find what is the name of the candidate from this resume
"""
    try:
        global response
        response = client.chat.completions.create(
            # model="gpt-3.5-turbo",
            model="gpt-4o-mini",
            # model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,  # Reduce randomness for consistent results
        )
        result = response.choices[0].message.content
        # Attempt to parse the JSON response
        try:
            # result_dict = json.loads(result)
            result_dict = json.loads(result.replace("```json", "").replace("```", ""))
            return result_dict
        except json.JSONDecodeError:
            print("Failed to parse JSON. Raw response:", result)
            return {"error": "Invalid JSON format in API response."}
    except Exception as e:
        print(f"Error communicating with OpenAI API: {e}")
        return {"error": str(e)}


def get_score(results, qualification_score=None):

    if qualification_score is None:
        qualification_score = {
            "Minimum Qualification": 1,
            "Preferred Qualification": 2,
            "Added Value": 3,
        }

    df = pd.DataFrame(results["qualifications"])
    df["score"] = df.apply(
        lambda row: (
            qualification_score[row["qualification_type"]]
            if row["true_or_false"]
            else 0
        ),
        axis=1,
    )
    scores = df[["qualification", "score"]].set_index("qualification")

    score_summary = (
        df.groupby("qualification_type")
        .sum()["score"]
        .to_frame()
        .reindex(["Minimum Qualification", "Preferred Qualification", "Added Value"])
        .reset_index()
    )
    score_summary["qualification_type"] = score_summary["qualification_type"].apply(
        lambda col: f"{col} Total Score"
    )
    score_summary = score_summary.set_index("qualification_type")

    candidate_info = pd.DataFrame(
        data={
            "Candidate Name": [results["name"]],
            "Email": results["email"],
            "Veteran": [results["is_veteran"]],
        }
    )

    scores = pd.concat([scores, score_summary]).T.reset_index(drop=True)
    scores = pd.concat([candidate_info, scores], axis=1)
    scores["Veteran Score"] = scores.apply(
        lambda row: (
            np.round(score_summary.sum()["score"] * 0.05, 2) if row["Veteran"] else 0
        ),
        axis=1,
    )
    scores["Final Score"] = scores[
        [
            "Minimum Qualification Total Score",
            "Preferred Qualification Total Score",
            "Added Value Total Score",
            "Veteran Score",
        ]
    ].sum(axis=1)
    scores["Summary"] = results["summarization"]
    scores = scores.set_index("Candidate Name")
    return scores
