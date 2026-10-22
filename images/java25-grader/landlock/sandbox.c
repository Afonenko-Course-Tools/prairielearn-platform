/*
 * A simple sandbox implementation using Landlock. Blocks access to files in the
 * /proc, /sys and /dev filesystems, but allows access to everything else. This
 * is intended to prevent students from using content of files like
 * /proc/self/maps to bypass the sandbox or retrieve information they shouldn't
 * have access to.
 *
 * landlock works on an allow-list basis, so we create a ruleset that allows
 * access to all current directories in the root filesystem except for /proc,
 * /sys and /dev, and then apply that ruleset to the current process before
 * executing the autograder.
 *
 * Code written with support from Gemini. Details on landlock can be found here:
 * https://man7.org/linux/man-pages/man7/landlock.7.html
 */
#define _GNU_SOURCE
#include <linux/landlock.h>
#include <linux/prctl.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <dirent.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <errno.h>

#define ACCESS_ALL                                                  \
  (LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR |     \
   LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_EXECUTE |     \
   LANDLOCK_ACCESS_FS_REMOVE_DIR | LANDLOCK_ACCESS_FS_REMOVE_FILE | \
   LANDLOCK_ACCESS_FS_MAKE_CHAR | LANDLOCK_ACCESS_FS_MAKE_DIR |     \
   LANDLOCK_ACCESS_FS_MAKE_REG | LANDLOCK_ACCESS_FS_MAKE_SOCK |     \
   LANDLOCK_ACCESS_FS_MAKE_FIFO | LANDLOCK_ACCESS_FS_MAKE_BLOCK |   \
   LANDLOCK_ACCESS_FS_TRUNCATE | LANDLOCK_ACCESS_FS_REFER |         \
   LANDLOCK_ACCESS_FS_MAKE_SYM)

void add_path_rule(int ruleset_fd, const char *path, __u64 access_mask) {
  int fd = open(path, O_PATH | O_CLOEXEC);
  if (fd < 0) {
    fprintf(stderr, "Failed to open path %s\n", path);
    perror("open");
    return;  // Skip directories we can't open (like some system mounts)
  }

  struct landlock_path_beneath_attr path_attr = {
      .allowed_access = access_mask,
      .parent_fd = fd,
  };

  if (syscall(SYS_landlock_add_rule, ruleset_fd, LANDLOCK_RULE_PATH_BENEATH,
              &path_attr, 0) < 0) {
    fprintf(stderr, "Failed to add rule for path %s\n", path);
    perror("syscall");
  }
  close(fd);
}

/* Единственное исключение к upstream /dev deny: проверенный null1:3 leaf. */
static int same_object(const struct stat *a, const struct stat *b) {
  int equal = a->st_dev == b->st_dev && a->st_ino == b->st_ino &&
         a->st_mode == b->st_mode && a->st_uid == b->st_uid &&
         a->st_gid == b->st_gid && a->st_nlink == b->st_nlink &&
         a->st_rdev == b->st_rdev && a->st_size == b->st_size &&
         a->st_mtim.tv_sec == b->st_mtim.tv_sec &&
         a->st_mtim.tv_nsec == b->st_mtim.tv_nsec &&
         a->st_ctim.tv_sec == b->st_ctim.tv_sec &&
         a->st_ctim.tv_nsec == b->st_ctim.tv_nsec;
  if (!equal) errno = ESTALE;
  return equal;
}

static int trusted_directory(const struct stat *s) {
  return S_ISDIR(s->st_mode) && s->st_uid == 0 && s->st_gid == 0 &&
         !(s->st_mode & 07022);
}

static int add_dev_null_rule(int ruleset_fd, __u64 access_mask) {
  int root_fd = -1, dev_fd = -1, null_fd = -1, result = -1;
  struct stat root, dev, leaf, current;
  root_fd = open("/", O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  if (root_fd < 0 || fstat(root_fd, &root) < 0) goto done;
  if (!trusted_directory(&root)) { errno = EPERM; goto done; }
  dev_fd = openat(root_fd, "dev", O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  if (dev_fd < 0 || fstat(dev_fd, &dev) < 0) goto done;
  if (!trusted_directory(&dev)) { errno = EPERM; goto done; }
  null_fd = openat(dev_fd, "null", O_PATH | O_NOFOLLOW | O_CLOEXEC);
  if (null_fd < 0 || fstat(null_fd, &leaf) < 0) goto done;
  if (!S_ISCHR(leaf.st_mode) || major(leaf.st_rdev) != 1 ||
      minor(leaf.st_rdev) != 3 || leaf.st_uid != 0 || leaf.st_gid != 0 ||
      (leaf.st_mode & 07777) != 0666 || leaf.st_nlink != 1) {
    errno = EPERM; goto done;
  }
  /* Не доверяем только fd либо только имени: проверяем обе связи до grant. */
  if (fstatat(root_fd, "dev", &current, AT_SYMLINK_NOFOLLOW) < 0 ||
      !same_object(&dev, &current) ||
      fstatat(dev_fd, "null", &current, AT_SYMLINK_NOFOLLOW) < 0 ||
      !same_object(&leaf, &current)) goto done;
  struct landlock_path_beneath_attr rule = {
      .allowed_access = access_mask & (LANDLOCK_ACCESS_FS_READ_FILE |
          LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_TRUNCATE),
      .parent_fd = null_fd,
  };
  if (syscall(SYS_landlock_add_rule, ruleset_fd, LANDLOCK_RULE_PATH_BENEATH,
              &rule, 0) < 0) goto done;
  /* Внутри операции полная metadata identity сохраняется, включая ctime. */
  if (fstat(root_fd, &current) < 0 || !same_object(&root, &current) ||
      fstat(dev_fd, &current) < 0 || !same_object(&dev, &current) ||
      fstat(null_fd, &current) < 0 || !same_object(&leaf, &current) ||
      fstatat(root_fd, "dev", &current, AT_SYMLINK_NOFOLLOW) < 0 ||
      !same_object(&dev, &current) ||
      fstatat(dev_fd, "null", &current, AT_SYMLINK_NOFOLLOW) < 0 ||
      !same_object(&leaf, &current)) goto done;
  result = 0;
done:
  if (null_fd >= 0 && close(null_fd) < 0) result = -1;
  if (dev_fd >= 0 && close(dev_fd) < 0) result = -1;
  if (root_fd >= 0 && close(root_fd) < 0) result = -1;
  return result;
}

int main(int argc, char *argv[]) {
  if (argc < 2) return 1;

  // Query the kernel's supported Landlock ABI version and adjust the mask.
  int abi = syscall(SYS_landlock_create_ruleset, NULL, 0,
                    LANDLOCK_CREATE_RULESET_VERSION);
  if (abi < 0) {
    perror("Landlock not supported by kernel");
    return 1;
  }
  __u64 access_mask = ACCESS_ALL;
  // Landlock ABI before v2 does not support REFER access, so we remove it from
  // the mask for older kernels.
  if (abi < 2) access_mask &= ~LANDLOCK_ACCESS_FS_REFER;
  // Landlock ABI before v3 does not support TRUNCATE access, so we remove it
  // from the mask for older kernels.
  if (abi < 3) access_mask &= ~LANDLOCK_ACCESS_FS_TRUNCATE;
  // Add similar guards for any future ABI-gated bits as needed.

  // Create a landlock ruleset that handles all filesystem access.
  struct landlock_ruleset_attr attr = {.handled_access_fs = access_mask};
  int ruleset_fd = syscall(SYS_landlock_create_ruleset, &attr, sizeof(attr), 0);
  if (ruleset_fd < 0) {
    perror("Landlock init failed");
    return 1;
  }

  // Scan / and add everything EXCEPT proc, sys and dev.
  DIR *d = opendir("/");
  if (!d) {
    perror("Failed to open root directory");
    return 1;
  }
  struct dirent *dir;
  while ((dir = readdir(d)) != NULL) {
    // We only add rules for directories. Paths are applied recursively, so we
    // don't need to add rules for individual files under those directories.
    // Files stored directly under / (like .dockerenv) become inaccessible, and
    // that's ok.
    if (dir->d_type != DT_DIR) continue;
    if (strcmp(dir->d_name, ".") == 0 || strcmp(dir->d_name, "..") == 0)
      continue;
    if (strcmp(dir->d_name, "proc") == 0 || strcmp(dir->d_name, "sys") == 0 ||
        strcmp(dir->d_name, "dev") == 0)
      continue;

    char full_path[512];
    snprintf(full_path, sizeof(full_path), "/%s", dir->d_name);
    add_path_rule(ruleset_fd, full_path, access_mask);
  }
  closedir(d);

  if (add_dev_null_rule(ruleset_fd, access_mask) < 0) {
    perror("Validated /dev/null rule failed");
    close(ruleset_fd);
    return 1;
  }

  // Blocks the process or its children from gaining new privileges, e.g., via
  // setuid binaries. This is required to use landlock.
  if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0) {
    perror("PR_SET_NO_NEW_PRIVS failed");
    return 1;
  }
  // Apply the landlock ruleset to the current process and its future children.
  if (syscall(SYS_landlock_restrict_self, ruleset_fd, 0)) {
    perror("Enforce failed");
    return 1;
  }
  close(ruleset_fd);

  execvp(argv[1], &argv[1]);
  perror("Exec failed");
  return 1;
}
