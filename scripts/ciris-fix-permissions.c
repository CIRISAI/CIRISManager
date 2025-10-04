/*
 * CIRIS Permission Fix Helper
 *
 * This is a setuid root program that fixes permissions for CIRIS agent directories.
 * It must be compiled and installed with proper permissions:
 *
 * Compilation and installation:
 *   gcc -o ciris-fix-permissions ciris-fix-permissions.c
 *   sudo chown root:root ciris-fix-permissions
 *   sudo chmod 4755 ciris-fix-permissions
 *   sudo mv ciris-fix-permissions /usr/local/bin/
 *
 * Usage:
 *   ciris-fix-permissions /opt/ciris/agents/agent-id
 *
 * Security notes:
 * - Only works on directories under /opt/ciris/agents/
 * - Sets ownership to uid 1000 (container user)
 * - Sets proper permissions for CIRIS requirements
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <dirent.h>
#include <errno.h>

#define AGENT_BASE_PATH "/opt/ciris/agents/"
#define CONTAINER_UID 1000
#define CONTAINER_GID 1000

int fix_directory_permissions_recursive(const char* path, mode_t dir_mode, mode_t file_mode) {
    // Set permissions on the directory itself
    if (chmod(path, dir_mode) != 0) {
        fprintf(stderr, "Failed to chmod %s: %s\n", path, strerror(errno));
        return -1;
    }

    // Set ownership on the directory
    if (chown(path, CONTAINER_UID, CONTAINER_GID) != 0) {
        fprintf(stderr, "Failed to chown %s: %s\n", path, strerror(errno));
        return -1;
    }

    // Recursively fix all files and subdirectories
    DIR* dir = opendir(path);
    if (dir == NULL) {
        // Directory might be empty or inaccessible, not necessarily an error
        return 0;
    }

    struct dirent* entry;
    while ((entry = readdir(dir)) != NULL) {
        // Skip . and ..
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }

        char full_path[1024];
        snprintf(full_path, sizeof(full_path), "%s/%s", path, entry->d_name);

        struct stat st;
        if (lstat(full_path, &st) != 0) {
            fprintf(stderr, "Failed to stat %s: %s\n", full_path, strerror(errno));
            continue;
        }

        // Set ownership
        if (lchown(full_path, CONTAINER_UID, CONTAINER_GID) != 0) {
            fprintf(stderr, "Failed to chown %s: %s\n", full_path, strerror(errno));
            continue;
        }

        // Set permissions (only for regular files and directories, not symlinks)
        if (S_ISDIR(st.st_mode)) {
            // Recursively fix subdirectory
            fix_directory_permissions_recursive(full_path, dir_mode, file_mode);
        } else if (S_ISREG(st.st_mode)) {
            // Fix file permissions
            if (chmod(full_path, file_mode) != 0) {
                fprintf(stderr, "Failed to chmod %s: %s\n", full_path, strerror(errno));
            }
        }
    }

    closedir(dir);
    return 0;
}

int fix_directory_permissions(const char* path, mode_t mode) {
    // For backward compatibility, call recursive version
    // Files get 600 (owner read/write) for secure directories
    mode_t file_mode = (mode == 0700) ? 0600 : 0644;
    return fix_directory_permissions_recursive(path, mode, file_mode);
}

int main(int argc, char *argv[]) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s /opt/ciris/agents/agent-id\n", argv[0]);
        return 1;
    }

    const char* agent_dir = argv[1];

    // Security check: ensure path starts with /opt/ciris/agents/
    if (strncmp(agent_dir, AGENT_BASE_PATH, strlen(AGENT_BASE_PATH)) != 0) {
        fprintf(stderr, "Error: Path must be under %s\n", AGENT_BASE_PATH);
        return 1;
    }

    // Check if directory exists
    struct stat st;
    if (stat(agent_dir, &st) != 0) {
        fprintf(stderr, "Error: Directory %s does not exist\n", agent_dir);
        return 1;
    }

    if (!S_ISDIR(st.st_mode)) {
        fprintf(stderr, "Error: %s is not a directory\n", agent_dir);
        return 1;
    }

    // Set effective uid to root for permission changes
    if (setuid(0) != 0) {
        fprintf(stderr, "Error: Failed to escalate privileges\n");
        return 1;
    }

    // Fix permissions for standard directories
    char path[512];
    int failed = 0;

    // data directory - 755
    snprintf(path, sizeof(path), "%s/data", agent_dir);
    if (fix_directory_permissions(path, 0755) != 0) failed = 1;

    // data_archive directory - 755
    snprintf(path, sizeof(path), "%s/data_archive", agent_dir);
    if (fix_directory_permissions(path, 0755) != 0) failed = 1;

    // logs directory - 755
    snprintf(path, sizeof(path), "%s/logs", agent_dir);
    if (fix_directory_permissions(path, 0755) != 0) failed = 1;

    // config directory - 755
    snprintf(path, sizeof(path), "%s/config", agent_dir);
    if (fix_directory_permissions(path, 0755) != 0) failed = 1;

    // audit_keys directory - 700
    snprintf(path, sizeof(path), "%s/audit_keys", agent_dir);
    if (fix_directory_permissions(path, 0700) != 0) failed = 1;

    // .secrets directory - 700
    snprintf(path, sizeof(path), "%s/.secrets", agent_dir);
    if (fix_directory_permissions(path, 0700) != 0) failed = 1;

    if (failed) {
        fprintf(stderr, "Some permissions could not be fixed\n");
        return 1;
    }

    printf("Successfully fixed permissions for %s\n", agent_dir);
    return 0;
}
