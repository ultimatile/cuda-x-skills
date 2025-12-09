#!/bin/bash
#
# Install skills to a project directory
#
# Usage:
#   ./install-skills.sh [options]
#
# Options:
#   --help              Show this help message
#   --list              List available skills
#   --all               Install all skills (default)
#   --skill <name>      Install specific skill(s) (can be used multiple times)
#
# Environment Variables:
#   SKILLS_INSTALL_PATH  Custom installation path (default: $PWD/.claude/skills)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default installation path
DEFAULT_INSTALL_PATH="$PWD/.claude/skills"
INSTALL_PATH="${SKILLS_INSTALL_PATH:-$DEFAULT_INSTALL_PATH}"

# Script directory (where this script is located)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_SOURCE_DIR="$SCRIPT_DIR/skills"

# Skills to install
INSTALL_ALL=true
SPECIFIC_SKILLS=()

# Functions
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

show_help() {
    cat << EOF
Install skills to a project directory

Usage:
  ./install-skills.sh [options]

Options:
  --help              Show this help message
  --list              List available skills
  --all               Install all skills (default)
  --skill <name>      Install specific skill(s) (can be used multiple times)

Environment Variables:
  SKILLS_INSTALL_PATH  Custom installation path (default: \$PWD/.claude/skills)

Examples:
  # Install all skills to default location
  ./install-skills.sh

  # List available skills
  ./install-skills.sh --list

  # Install all skills to custom location
  SKILLS_INSTALL_PATH=/path/to/project/.claude/skills ./install-skills.sh

  # Install specific skills
  ./install-skills.sh --skill my-skill --skill another-skill

  # Install to custom path with specific skill
  SKILLS_INSTALL_PATH=/path/to/project ./install-skills.sh --skill my-skill

EOF
}

list_available_skills() {
    echo ""
    print_info "Available skills in $SKILLS_SOURCE_DIR:"
    echo ""

    if [ ! -d "$SKILLS_SOURCE_DIR" ]; then
        print_error "Skills directory not found: $SKILLS_SOURCE_DIR"
        return 1
    fi

    local found=false
    for skill_dir in "$SKILLS_SOURCE_DIR"/*/ ; do
        if [ -d "$skill_dir" ]; then
            local skill_name=$(basename "$skill_dir")
            if [ -f "$skill_dir/SKILL.md" ]; then
                # Extract description from YAML frontmatter if available
                local description=$(awk '/^---$/,/^---$/{if(/^description:/) {sub(/^description: */, ""); print; exit}}' "$skill_dir/SKILL.md")
                if [ -n "$description" ]; then
                    echo "  • $skill_name"
                    echo "    $description"
                else
                    echo "  • $skill_name"
                fi
                found=true
            fi
        fi
    done

    if [ "$found" = false ]; then
        print_warn "No skills found (no SKILL.md files)"
    fi
    echo ""
}

install_skill() {
    local skill_name=$1
    local source_path="$SKILLS_SOURCE_DIR/$skill_name"
    local dest_path="$INSTALL_PATH/$skill_name"

    if [ ! -d "$source_path" ]; then
        print_error "Skill not found: $skill_name"
        return 1
    fi

    # Create destination directory
    mkdir -p "$INSTALL_PATH"

    # Remove existing installation if present
    if [ -d "$dest_path" ]; then
        print_warn "Removing existing installation: $dest_path"
        rm -rf "$dest_path"
    fi

    # Copy skill
    print_info "Installing $skill_name..."
    cp -r "$source_path" "$dest_path"

    print_info "✓ Installed $skill_name to $dest_path"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --help)
            show_help
            exit 0
            ;;
        --list)
            list_available_skills
            exit 0
            ;;
        --all)
            INSTALL_ALL=true
            shift
            ;;
        --skill)
            INSTALL_ALL=false
            if [ -z "$2" ] || [[ "$2" == --* ]]; then
                print_error "--skill requires a skill name"
                exit 1
            fi
            SPECIFIC_SKILLS+=("$2")
            shift 2
            ;;
        *)
            print_error "Unknown option: $1"
            echo ""
            show_help
            exit 1
            ;;
    esac
done

# Main installation
echo ""
echo "╔════════════════════════════════════════════════════╗"
echo "║       Skills Installation                          ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""
print_info "Installation path: $INSTALL_PATH"
echo ""

# Check if source directory exists
if [ ! -d "$SKILLS_SOURCE_DIR" ]; then
    print_error "Skills source directory not found: $SKILLS_SOURCE_DIR"
    exit 1
fi

# Install selected skills
if [ "$INSTALL_ALL" = true ]; then
    print_info "Installing all skills..."
    echo ""

    # Find all directories with SKILL.md
    skill_count=0
    for skill_dir in "$SKILLS_SOURCE_DIR"/*/ ; do
        if [ -d "$skill_dir" ]; then
            skill_name=$(basename "$skill_dir")
            if [ -f "$skill_dir/SKILL.md" ]; then
                install_skill "$skill_name"
                skill_count=$((skill_count + 1))
            else
                print_warn "Skipping $skill_name (no SKILL.md found)"
            fi
        fi
    done

    if [ $skill_count -eq 0 ]; then
        print_error "No valid skills found in $SKILLS_SOURCE_DIR"
        exit 1
    fi
else
    # Install specific skills
    if [ ${#SPECIFIC_SKILLS[@]} -eq 0 ]; then
        print_error "No skills specified. Use --skill <name> or --all"
        exit 1
    fi

    for skill_name in "${SPECIFIC_SKILLS[@]}"; do
        install_skill "$skill_name"
    done
fi

echo ""
echo "╔════════════════════════════════════════════════════╗"
echo "║       Installation Complete!                       ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""
print_info "Skills installed to: $INSTALL_PATH"
echo ""
print_info "Next steps:"
echo ""
echo "  Skills have been copied to: $INSTALL_PATH"
echo ""
echo "  Choose ONE of the following methods to use these skills:"
echo ""
echo "  Option 1: Direct use (Recommended for single project)"
echo "    → Skills in .claude/skills/ are automatically detected"
echo "    → No additional configuration needed"
echo ""
echo "  Option 2: Plugin installation (Recommended for multiple projects)"
echo "    → In Claude Code, run: /plugin install $SCRIPT_DIR"
echo "    → Makes skills available across projects"
echo ""
echo "  Option 3: Team-wide marketplace (Advanced)"
echo "    → Add to .claude/settings.json in your project:"
echo "    → See README.md for detailed instructions"
echo ""
print_info "Next: Check each skill's SKILL.md for specific dependencies and setup"
echo ""
