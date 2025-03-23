import sys
from mothics.command_line import MothicsCLI

if __name__ == '__main__':
    cli = MothicsCLI()
    if len(sys.argv) > 1:
        # Execute the command passed as argument
        command = " ".join(sys.argv[1:])
        cli.onecmd(command)
    # Drop into the interactive CLI
    cli.cmdloop()
