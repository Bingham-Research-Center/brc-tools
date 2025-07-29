from html_to_markdown import convert_to_markdown
import requests

def extract_markdown_from_website(url: str) -> str:
    """Fetches the content of a webpage and converts it to Markdown format."""
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad responses
        return convert_to_markdown(response.text)
    except requests.RequestException as e:
        return f"Error fetching data from {url}: {e}"


if __name__ == "__main__":
    # Testing
    url = "https://www.usu.edu/binghamresearch/cumulative-research-summary"
    markdown_content = extract_markdown_from_website(url)
    print(markdown_content)
