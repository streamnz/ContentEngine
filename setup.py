from setuptools import setup, find_packages

setup(
    name="content_engine",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        "playwright==1.41.2",
        "mysql-connector-python==8.3.0",
        "python-dotenv==1.0.0",
        "requests==2.31.0",
        "beautifulsoup4==4.12.2",
        "anthropic==0.18.1",
        "openai==1.12.0"
    ],
) 