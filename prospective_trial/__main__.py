from .cli import main
from .qualification import QualificationPaused
import sys

try:
    main()
except QualificationPaused as error:
    print('PAUSED: '+str(error), file=sys.stderr)
    raise SystemExit(2)
