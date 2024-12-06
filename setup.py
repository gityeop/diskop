from setuptools import setup, find_packages

setup(
    name="diskop",
    version="1.0.0",
    description="Terminal User Interface (TUI) disk management tool for macOS",
    author="Sangyeob Im",
    author_email="",
    url="https://github.com/gityeop/diskop",
    packages=find_packages(),
    py_modules=["diskop"],
    install_requires=[
        "readchar>=4.0.5",
    ],
    entry_points={
        "console_scripts": [
            "diskop=diskop:main",
        ],
    },
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: MacOS",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.6",
)
