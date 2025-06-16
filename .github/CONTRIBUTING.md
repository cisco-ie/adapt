# Contributing to ADAPT

Thank you for your interest in contributing to ADAPT! This document provides guidelines and instructions for contributing to this project.

## Code of Conduct

By participating in this project, you agree to abide by our Code of Conduct. Please read it before contributing.

## How to Contribute

### Reporting Bugs

Before submitting a bug report:

1. Check if the bug has already been reported by searching on GitHub under [Issues](https://github.com/cisco-ie/adapt/issues).
2. If you're unable to find an open issue addressing the problem, [open a new one](https://github.com/cisco-ie/adapt/issues/new/choose) using the Bug Report template.

### Feature Requests

We welcome feature requests:

1. Check if the feature has already been requested by searching on GitHub under [Issues](https://github.com/cisco-ie/adapt/issues).
2. If you're unable to find an open feature request for your idea, [open a new one](https://github.com/cisco-ie/adapt/issues/new/choose) using the Feature Request template.

### Pull Requests

1. Fork the repository.
2. Create a new branch: `git checkout -b feature/your-feature-name` or `git checkout -b fix/your-fix-name`.
3. Make your changes.
4. Run the tests to make sure everything works.
5. Commit your changes using a descriptive commit message.
6. Push to your branch: `git push origin feature/your-feature-name`.
7. Create a Pull Request.

## Development Setup

### Prerequisites

- Python 3.12+
- pip

### Setting Up Development Environment

```bash
# Clone the repository
git clone https://github.com/cisco-ie/adapt.git
cd adapt

# Create and activate a virtual environment
python -m venv venv
# On Windows
.\venv\Scripts\activate
# On Unix or MacOS
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Coding Style

Please follow these style guidelines:

1. Use consistent code formatting
2. Write descriptive commit messages
3. Include comments for complex sections of code
4. Follow PEP 8 for Python code

## Documentation

Update documentation when making changes:

1. Update README.md if necessary
2. Update docstrings for any modified functions/classes
3. Add/update examples if relevant

## Golden Rules

1. When making code changes, never remove code that is commented out.
2. Always maintain backward compatibility unless there's a compelling reason not to.
3. Document all non-obvious code behavior.

## Additional Resources

- [Project Documentation](link-to-documentation)
- [Issue Tracker](https://github.com/cisco-ie/adapt/issues)

Thank you for contributing to ADAPT!
