"""Phase 1 audit CLI only. Does not generate predictions."""
import argparse
import json
from pathlib import Path
from src.config import DEFAULT_AUDIT_PATH
from src.data.audit import build_audit
from src.data.currency import CurrencyConverter
from src.data.loader import load_all_data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-root', type=Path)
    parser.add_argument('--audit-path', type=Path, default=DEFAULT_AUDIT_PATH)
    args = parser.parse_args()
    data = load_all_data(args.dataset_root)
    CurrencyConverter(data.exchange_rates)
    report = json.dumps(build_audit(data), indent=2, sort_keys=True) + '\n'
    target = args.audit_path.resolve()
    if target == data.root or data.root in target.parents:
        parser.error('--audit-path must be outside the input dataset')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding='utf-8')
    print(report, end='')
    print(f'Audit saved to {target}')


if __name__ == '__main__':
    main()
