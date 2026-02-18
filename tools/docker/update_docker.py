#!/usr/bin/env python3
"""
Docker Update Script
This script rebuilds the Docker image when you add new Python libraries.
"""

import subprocess
import sys
import os
import tempfile
import shutil

# Configuration
IMAGE_NAME = "ai_sandbox_image"
CONTAINER_NAME = "ai_sandbox_env"
DOCKERFILE_PATH = "Dockerfile"
WORKSPACE_PATH = "/workspace"

def run_command(cmd, description, show_output=True):
    """Run a shell command and handle errors."""
    print(f"\n{'='*60}")
    print(f"{description}")
    print(f"{'='*60}")
    print(f"Running: {' '.join(cmd)}\n")
    
    try:
        if show_output:
            # Stream output in real-time
            result = subprocess.run(cmd, check=True)
        else:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            if result.stdout:
                print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        return False

def check_docker_installed():
    """Check if Docker is installed."""
    try:
        subprocess.run(
            ["docker", "--version"],
            check=True,
            capture_output=True
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Docker is not installed or not in PATH")
        return False

def backup_container_files():
    """Backup files from the existing container before removing it."""
    print(f"\n💾 Checking for files to backup from '{CONTAINER_NAME}'...")
    
    # Check if container exists and is running
    result = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name={CONTAINER_NAME}", "--format", "{{.Names}}:{{.State}}"],
        capture_output=True,
        text=True
    )
    
    if CONTAINER_NAME not in result.stdout:
        print("No existing container found - nothing to backup")
        return None
    
    # Check if container is running, start it if not
    if "running" not in result.stdout.lower():
        print(f"Container is stopped. Starting it to backup files...")
        subprocess.run(["docker", "start", CONTAINER_NAME], capture_output=True)
    
    # Check if workspace has any files
    check_files = subprocess.run(
        ["docker", "exec", CONTAINER_NAME, "ls", "-A", WORKSPACE_PATH],
        capture_output=True,
        text=True
    )
    
    if check_files.returncode != 0 or not check_files.stdout.strip():
        print(f"No files found in {WORKSPACE_PATH}")
        return None
    
    # Create temporary directory for backup
    temp_dir = tempfile.mkdtemp(prefix="docker_backup_")
    print(f"Found files in container workspace:")
    print(check_files.stdout)
    print(f"Backing up to: {temp_dir}")
    
    # Copy each file from container
    files = check_files.stdout.strip().split('\n')
    backed_up = 0
    for filename in files:
        if not filename:
            continue
        source_path = f"{WORKSPACE_PATH}/{filename}"
        
        # Use docker exec with cat to copy file
        cat_cmd = ["docker", "exec", CONTAINER_NAME, "cat", source_path]
        dest_path = os.path.join(temp_dir, filename)
        
        try:
            with open(dest_path, "wb") as f:
                result = subprocess.run(cat_cmd, stdout=f, stderr=subprocess.PIPE)
                if result.returncode == 0:
                    file_size = os.path.getsize(dest_path)
                    print(f"  ✓ Backed up: {filename} ({file_size} bytes)")
                    backed_up += 1
                else:
                    print(f"  ✗ Failed to backup: {filename} - {result.stderr.decode()}")
        except Exception as e:
            print(f"  ✗ Error backing up {filename}: {e}")
    
    if backed_up == 0:
        print("⚠️  No files were successfully backed up")
        shutil.rmtree(temp_dir)
        return None
    
    print(f"✅ Backed up {backed_up} file(s)")
    return temp_dir

def restore_files_to_container(backup_dir):
    """Restore backed up files to the new container."""
    if not backup_dir or not os.path.exists(backup_dir):
        print("\n📁 No backup to restore")
        return
    
    print(f"\n📥 Restoring files to new container...")
    
    files = os.listdir(backup_dir)
    if not files:
        print("No files to restore")
        return
    
    restored = 0
    for filename in files:
        source_path = os.path.join(backup_dir, filename)
        dest_path = f"{WORKSPACE_PATH}/{filename}"
        
        try:
            # Use docker exec with tee to copy file
            with open(source_path, "rb") as f:
                file_data = f.read()
                result = subprocess.run(
                    ["docker", "exec", "-i", CONTAINER_NAME, "tee", dest_path],
                    input=file_data,
                    capture_output=True
                )
                if result.returncode == 0:
                    print(f"  ✓ Restored: {filename} ({len(file_data)} bytes)")
                    restored += 1
                else:
                    print(f"  ✗ Failed to restore: {filename} - {result.stderr.decode()}")
        except Exception as e:
            print(f"  ✗ Error restoring {filename}: {e}")
    
    print(f"✅ Restored {restored} file(s)")
    
    # Verify restoration
    print("\n🔍 Verifying files in new container:")
    verify = subprocess.run(
        ["docker", "exec", CONTAINER_NAME, "ls", "-lh", WORKSPACE_PATH],
        capture_output=True,
        text=True
    )
    if verify.stdout:
        print(verify.stdout)
    
    # Cleanup backup directory
    try:
        shutil.rmtree(backup_dir)
        print(f"Cleaned up backup directory")
    except Exception as e:
        print(f"Warning: Could not clean up {backup_dir}: {e}")

def stop_and_remove_container():
    """Stop and remove existing container if it exists."""
    print(f"\n🛑 Checking for existing container '{CONTAINER_NAME}'...")
    
    # Check if container exists
    result = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name={CONTAINER_NAME}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True
    )
    
    if CONTAINER_NAME in result.stdout:
        print(f"Found existing container. Stopping and removing...")
        
        # Stop container
        subprocess.run(
            ["docker", "stop", CONTAINER_NAME],
            capture_output=True
        )
        
        # Remove container
        subprocess.run(
            ["docker", "rm", CONTAINER_NAME],
            capture_output=True
        )
        
        print(f"✅ Container '{CONTAINER_NAME}' removed")
    else:
        print(f"No existing container found")

def remove_old_image():
    """Remove old Docker image if it exists."""
    print(f"\n🗑️  Checking for existing image '{IMAGE_NAME}'...")
    
    # Check if image exists
    result = subprocess.run(
        ["docker", "images", "-q", IMAGE_NAME],
        capture_output=True,
        text=True
    )
    
    if result.stdout.strip():
        print(f"Found existing image. Removing...")
        subprocess.run(
            ["docker", "rmi", IMAGE_NAME],
            capture_output=True
        )
        print(f"✅ Image '{IMAGE_NAME}' removed")
    else:
        print(f"No existing image found")

def build_docker_image():
    """Build the Docker image with updated dependencies."""
    print(f"\n🔨 Building Docker image '{IMAGE_NAME}'...")
    print("(This may take a few minutes...)\n")
    
    # Build image with real-time output
    cmd = ["docker", "build", "-t", IMAGE_NAME, "-f", DOCKERFILE_PATH, "."]
    
    try:
        result = subprocess.run(cmd, check=True)
        print(f"\n✅ Successfully built image '{IMAGE_NAME}'")
        return True
    except subprocess.CalledProcessError:
        print(f"\n❌ Failed to build image")
        return False

def start_new_container():
    """Start the new container with the updated image."""
    print(f"\n🚀 Starting new container '{CONTAINER_NAME}'...")
    
    run_cmd = [
        "docker", "run", "-d", "-t",
        "--name", CONTAINER_NAME,
        "--network", "none",
        "--memory", "1024m",
        "--cpus", "2",
        "--cap-drop=ALL",
        "--read-only",
        "--tmpfs", "/tmp",
        "--tmpfs", f"{WORKSPACE_PATH}:exec,mode=1777",
        IMAGE_NAME, "bash"
    ]
    
    try:
        result = subprocess.run(run_cmd, check=True, capture_output=True, text=True)
        print(f"✅ Container started successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to start container: {e.stderr}")
        return False

def generate_help_file():
    """Generate a help.txt file documenting the Docker environment."""
    print(f"\n📝 Generating help.txt file...")
    
    try:
        # Create a temporary container to extract package information
        print("Creating temporary container to gather package information...")
        
        # Start a temporary container
        temp_container = f"{CONTAINER_NAME}_temp"
        subprocess.run(
            ["docker", "run", "-d", "--name", temp_container, IMAGE_NAME, "tail", "-f", "/dev/null"],
            capture_output=True,
            check=True
        )
        
        # Get Python version
        python_version = subprocess.run(
            ["docker", "exec", temp_container, "python", "--version"],
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        
        # Get pip list
        pip_list = subprocess.run(
            ["docker", "exec", temp_container, "pip", "list"],
            capture_output=True,
            text=True,
            check=True
        ).stdout
        
        # Get Java version
        java_version = subprocess.run(
            ["docker", "exec", temp_container, "java", "-version"],
            capture_output=True,
            text=True,
            check=True
        ).stderr.strip()  # Java outputs to stderr
        
        # Get javac version
        javac_version = subprocess.run(
            ["docker", "exec", temp_container, "javac", "-version"],
            capture_output=True,
            text=True,
            check=True
        ).stderr.strip()
        
        # Get system info
        os_info = subprocess.run(
            ["docker", "exec", temp_container, "cat", "/etc/os-release"],
            capture_output=True,
            text=True,
            check=True
        ).stdout
        
        # Clean up temporary container
        subprocess.run(["docker", "stop", temp_container], capture_output=True)
        subprocess.run(["docker", "rm", temp_container], capture_output=True)
        
        # Generate help.txt content
        help_content = f"""
╔════════════════════════════════════════════════════════════════════════════╗
║                   AI SANDBOX DOCKER ENVIRONMENT HELP                       ║
╚════════════════════════════════════════════════════════════════════════════╝

IMPORTANT: This is an ISOLATED, OFFLINE environment with NO INTERNET ACCESS
═══════════════════════════════════════════════════════════════════════════

ENVIRONMENT INFORMATION
─────────────────────────
{python_version}
Base Image: python:3.10-slim
User: sandboxuser (non-root)
Working Directory: /workspace

JAVA ENVIRONMENT
─────────────────────────
{java_version}
{javac_version}

SYSTEM INFORMATION
─────────────────────────
{os_info}

AVAILABLE PYTHON PACKAGES
─────────────────────────
{pip_list}

SYSTEM DEPENDENCIES (apt packages)
───────────────────────────────────
• build-essential (gcc, g++, make, etc.)
• libfreetype6-dev (FreeType library for text rendering)
• libpng-dev (PNG image library)
• default-jdk (Java Development Kit - includes javac and java)

KEY FEATURES & CAPABILITIES
────────────────────────────
✓ Python code execution (isolated)
✓ Mathematical computations (numpy, scipy, sympy)
✓ Data analysis (pandas)
✓ Plotting and visualization (matplotlib)
✓ Image processing (pillow)
✓ PDF manipulation (pypdf)
✓ Java compilation and execution
✓ C/C++ compilation (gcc/g++)

LIMITATIONS & RESTRICTIONS
───────────────────────────
✗ NO internet access (network isolated)
✗ NO pip install (cannot install new packages at runtime)
✗ Limited system access (runs as non-root user)
✗ Cannot access host filesystem (except shared /workspace)
✗ Cannot make external API calls or download resources

USAGE NOTES
────────────
• All code runs in the /workspace directory
• Files created in /workspace persist only during container lifetime
• The environment is stateless - each execution starts fresh
• Standard input/output is captured and returned
• Maximum execution time is enforced by the bot
• Resource usage (CPU/memory) is monitored

UPDATING THE ENVIRONMENT
─────────────────────────
To add new Python packages or system dependencies:
1. Edit the Dockerfile in the project root
2. Add packages to the RUN pip install line
3. Run: python update_docker.py
4. Restart the bot

For more information, see the README.md in the project directory.

Generated on: {subprocess.run(['date'], capture_output=True, text=True).stdout.strip()}
Docker Image: {IMAGE_NAME}
════════════════════════════════════════════════════════════════════════════
"""
        
        # Write to help.txt
        with open("help.txt", "w") as f:
            f.write(help_content)
        
        print("✅ help.txt generated successfully")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Error generating help.txt: {e}")
        # Clean up temporary container if it exists
        subprocess.run(["docker", "stop", temp_container], capture_output=True)
        subprocess.run(["docker", "rm", temp_container], capture_output=True)
        return False
    except Exception as e:
        print(f"❌ Error generating help.txt: {e}")
        return False

def main():
    """Main function to update Docker setup."""
    print("="*60)
    print("🐳 Docker Update Script")
    print("="*60)
    
    # Check if we're in the right directory
    if not os.path.exists(DOCKERFILE_PATH):
        print(f"❌ Error: {DOCKERFILE_PATH} not found in current directory")
        print(f"Current directory: {os.getcwd()}")
        print("Please run this script from the project root directory.")
        sys.exit(1)
    
    # Check if Docker is installed
    if not check_docker_installed():
        sys.exit(1)
    
    print("\n📋 This script will:")
    print("  1. Backup files from the existing container")
    print("  2. Stop and remove the old container")
    print("  3. Rebuild the image with updated dependencies (uses cache)")
    print("  4. Start a new container")
    print("  5. Restore your files to the new container")
    
    response = input("\n⚠️  Do you want to continue? (yes/no): ").lower().strip()
    if response not in ['yes', 'y']:
        print("Aborted by user")
        sys.exit(0)
    
    # Step 1: Backup files from old container
    backup_dir = backup_container_files()
    
    # Step 2: Stop and remove container
    stop_and_remove_container()
    
    # Step 3: Build new image (keeps old image for layer caching)
    if not build_docker_image():
        print("\n❌ Build failed. Please check the errors above.")
        if backup_dir:
            print(f"⚠️  Your files are backed up in: {backup_dir}")
        sys.exit(1)
    
    # Clean up dangling images left over from the rebuild
    print("\n🧹 Cleaning up old image layers...")
    subprocess.run(["docker", "image", "prune", "-f"], capture_output=True)
    
    # Step 4: Start new container
    if not start_new_container():
        print("\n❌ Failed to start container.")
        if backup_dir:
            print(f"⚠️  Your files are backed up in: {backup_dir}")
        sys.exit(1)
    
    # Step 5: Restore files
    restore_files_to_container(backup_dir)
    
    # Step 4: Generate help.txt
    generate_help_file()
    
    print("\n" + "="*60)
    print("✅ Docker image updated successfully!")
    print("="*60)
    print(f"\nYou can now run containers using the '{IMAGE_NAME}' image.")
    print("\nNext steps:")
    print("  - Start your bot: python bot.py")
    print("  - The docker_manager.py will automatically use the updated image")
    print("  - Check help.txt for environment documentation")

if __name__ == "__main__":
    main()
