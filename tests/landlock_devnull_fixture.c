/* Только syscall fixtures: этот файл не входит в grading image. */
#define _GNU_SOURCE // NOLINT(bugprone-reserved-identifier): glibc feature-test
                    // macro
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/landlock.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/sysmacros.h>
#include <unistd.h>

static int scenario, fixture_abi = 3, target_executed, leaf_rule, grant_done,
                     bad_flags;
static unsigned closed_fds, opened_fds;
static unsigned long long allowed;
static int fake_open(const char *p, int flags, ...) {
  if (strcmp(p, "/") != 0) {
    errno = EINVAL;
    return -1;
  }
  if (((unsigned int)flags &
       (unsigned int)(O_PATH | O_CLOEXEC | O_NOFOLLOW | O_DIRECTORY)) !=
      (O_PATH | O_CLOEXEC | O_NOFOLLOW | O_DIRECTORY))
    bad_flags = 1;
  if (scenario == 12) {
    errno = EACCES;
    return -1;
  }
  opened_fds |= 1U << 6U;
  return 6;
}
static int fake_openat(int fd, const char *p, int flags, ...) {
  if (((unsigned int)flags & (unsigned int)(O_PATH | O_CLOEXEC | O_NOFOLLOW)) !=
      (O_PATH | O_CLOEXEC | O_NOFOLLOW))
    bad_flags = 1;
  if (fd == 6 && strcmp(p, "dev") == 0) {
    if (!((unsigned int)flags & (unsigned int)O_DIRECTORY))
      bad_flags = 1;
    if (scenario == 13) {
      errno = EACCES;
      return -1;
    }
    opened_fds |= 1U << 7U;
    return 7;
  }
  if (fd == 7 && strcmp(p, "null") == 0) {
    if (scenario == 14) {
      errno = EACCES;
      return -1;
    }
    opened_fds |= 1U << 8U;
    return 8;
  }
  errno = EINVAL;
  return -1;
}
static void fill(int fd, struct stat *s) {
  // NOLINTNEXTLINE(clang-analyzer-security.insecureAPI.DeprecatedOrUnsafeBufferHandling): exact size of the fixture-owned stat object.
  memset(s, 0, sizeof(*s));
  s->st_dev = 1;
  s->st_nlink = 2;
  s->st_mode = S_IFDIR | 0755;
  switch (fd) {
  case 6:
    s->st_ino = 6;
    break;
  case 7:
    s->st_ino = 7;
    break;
  case 8:
    s->st_ino = 8;
    break;
  default:
    abort();
  }
  if (fd == 8) {
    s->st_mode = S_IFCHR | 0666;
    s->st_nlink = 1;
    s->st_rdev = makedev(1, 3);
  }
  if (fd == 8 && scenario == 1)
    s->st_mode = S_IFLNK | 0777;
  if (fd == 8 && scenario == 2)
    s->st_mode = S_IFREG | 0666;
  if (fd == 8 && scenario == 3)
    s->st_rdev = makedev(1, 5);
  if (fd == 8 && scenario == 4)
    s->st_uid = 1001;
  if (fd == 8 && scenario == 5)
    s->st_gid = 1001;
  if (fd == 8 && scenario == 6)
    s->st_mode = S_IFCHR | 0660;
  if (fd == 8 && scenario == 7)
    s->st_nlink = 2;
  if (fd == 7 && scenario == 8)
    s->st_mode = S_IFDIR | 0777;
  if (fd == 7 && scenario == 9)
    s->st_uid = 1001;
  if (fd == 6 && scenario == 10)
    s->st_mode = S_IFDIR | 0777;
  if (fd == 7 && scenario == 11)
    s->st_mode = S_IFLNK | 0777;
  if (fd == 7 && scenario == 21)
    s->st_gid = 1001;
  if (fd == 8 && scenario == 22)
    s->st_mode = S_IFCHR | 04666;
  if (fd == 6 && scenario == 23)
    s->st_uid = 1001;
  if (fd == 6 && scenario == 24)
    s->st_gid = 1001;
  if (fd == 8 && scenario == 25)
    s->st_nlink = 0;
  if (grant_done && scenario == 19 && fd == 8)
    s->st_ctim.tv_nsec = 1;
}
static int fake_fstat(int fd, struct stat *s) {
  if (scenario == 15) {
    errno = EIO;
    return -1;
  }
  fill(fd, s);
  return 0;
}
static int fake_fstatat(int fd, const char *p, struct stat *s, int flags) {
  if (flags != AT_SYMLINK_NOFOLLOW)
    bad_flags = 1;
  int target = fd == 6 && !strcmp(p, "dev")    ? 7
               : fd == 7 && !strcmp(p, "null") ? 8
                                               : -1;
  if (target < 0 || scenario == 16) {
    errno = ENOENT;
    return -1;
  }
  fill(target, s);
  if (scenario == 17)
    s->st_ino = 999;
  return 0;
}
static int fake_close(int fd) {
  closed_fds |= 1U << (unsigned int)fd;
  if (fd == 8 && scenario == 20) {
    errno = EIO;
    return -1;
  }
  return 0;
}
static DIR *fake_opendir(const char *p) {
  (void)p;
  return (DIR *)1;
}
static struct dirent *fake_readdir(DIR *d) {
  (void)d;
  return NULL;
}
static int fake_closedir(DIR *d) {
  (void)d;
  return 0;
}
static int fake_prctl(int option, ...) {
  (void)option;
  return 0;
}
static int fake_execvp(const char *file, char *const argv[]) {
  (void)file;
  (void)argv;
  target_executed++;
  errno = EIO;
  return -1;
}
static long fake_syscall(long nr, ...) {
  va_list args;
  va_start(args, nr);
  long result = -1;
  if (nr == SYS_landlock_create_ruleset) {
    void *attr = va_arg(args, void *);
    result = attr ? 5 : fixture_abi;
  }
  if (nr == SYS_landlock_add_rule) {
    (void)va_arg(args, int);
    (void)va_arg(args, int);
    struct landlock_path_beneath_attr *a = va_arg(args, void *);
    leaf_rule++;
    allowed = a->allowed_access;
    grant_done = 1;
    if (a->parent_fd != 8)
      bad_flags = 1;
    result = scenario == 18 ? -1 : 0;
    errno = EPERM;
  }
  if (nr == SYS_landlock_restrict_self)
    result = 0;
  va_end(args);
  return result;
}
static int upstream_sandbox_main(int argc, char *argv[]);
#define main upstream_sandbox_main
#define open fake_open
#define openat fake_openat
#define fstat fake_fstat
#define fstatat fake_fstatat
#define close fake_close
#define opendir fake_opendir
#define readdir fake_readdir
#define closedir fake_closedir
#define prctl fake_prctl
#define execvp fake_execvp
#define syscall fake_syscall
// NOLINTNEXTLINE(bugprone-suspicious-include): inject syscall fakes into the production C translation unit.
#include "../images/java25-grader/landlock/sandbox.c"
#undef main
static int fixture_integer(const char *text) {
  char *end = NULL;
  errno = 0;
  long value = strtol(text, &end, 10);
  if (errno != 0 || end == text || *end != '\0' || value < INT_MIN ||
      value > INT_MAX) {
    fputs("Invalid fixture integer\n", stderr);
    exit(2);
  }
  return (int)value;
}
int main(int argc, char **argv) {
  scenario = argc > 1 ? fixture_integer(argv[1]) : 0;
  fixture_abi = argc > 2 ? fixture_integer(argv[2]) : 3;
  char command_name[] = "sandbox", target_name[] = "never-executed";
  char *command[] = {command_name, target_name, NULL};
  int rc = upstream_sandbox_main(2, command);
  printf("{\"rc\":%d,\"executed\":%d,\"leafRules\":%d,\"allowed\":%llu,"
         "\"closedFDs\":%u,\"badFlags\":%d,\"leakedFDs\":%u}\n",
         rc, target_executed, leaf_rule, allowed, closed_fds, bad_flags,
         opened_fds & ~closed_fds);
  return 0;
}
