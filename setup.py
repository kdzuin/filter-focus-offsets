from setuptools import find_packages, setup

setup(
    name="filter-focus-offsets",
    version="0.1.0",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "filter-focus-offsets=filter_focus_offsets.cli:main",
        ],
    },
    install_requires=[
        "astropy",
        "numpy",
    ],
    description="Estimate ASIAIR filter focus offsets from Light FITS frames",
    author="Konstantin Dziuin",
    python_requires=">=3.9",
)
