# Xbox LFG Session Tool

Small multithreaded script to create and maintain Xbox Looking For Group (LFG) sessions.

## Files you need

- `tokens.txt` - one Xbox Live authorization token per line
- `lfg_messages.txt` - (optional) LFG description texts, one per line

## Install

pip install -r requirements.txt

## Usage

python main.py --threads 15 --max-active 8 --texts lfg_messages.txt

python main.py --threads 50 --max-active 0
