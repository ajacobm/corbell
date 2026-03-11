# Contributing to Corbell

First off, thank you for considering contributing to Corbell! It's people like you that make Corbell such a great tool for the community.

Corbell is an Apache-licensed open-source project designed to bridge the gap between complex multi-repo architectures and developer understanding.

## Code of Conduct

By participating in this project, you agree to abide by the standard open-source Code of Conduct. Please be respectful and professional in all interactions.

## How Can I Contribute?

### Reporting Bugs

If you find a bug, please search the issue tracker to see if it has already been reported. If not, open a new issue and include:
- A clear, descriptive title.
- Steps to reproduce the issue.
- Your environment (OS, Python version).
- Expected vs. actual behavior.

### Suggesting Enhancements

We welcome ideas for new features! To suggest an enhancement:
- Check existing issues for similar proposals.
- Open a new issue describing the feature and its use case.

### Pull Requests

1. **Fork the repo** and create your branch from `main`.
2. **Install dependencies**: `pip install -r requirements.txt`.
3. **Make your changes**. If you've added code that should be tested, add tests.
4. **Run tests**: `python3.11 -m pytest tests/`.
5. **Ensure your code follows PEP 8** and is well-documented.
6. **Submit a pull request** with a clear description of your changes.

## Development Setup

Corbell requires Python 3.11+.

```bash
# Clone your fork
git clone https://github.com/your-username/Corbell.git
cd Corbell

# Create a virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -e .
```

## Licensing

By contributing to Corbell, you agree that your contributions will be licensed under the Apache License, Version 2.0.

---
Thank you for helping us build the future of architecture intelligence!
