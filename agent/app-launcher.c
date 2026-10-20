/*
 * SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The executable of the packaged "Krita Agent.app" (Contents/MacOS/krita). It does three things and then becomes Krita:
 *
 *   1. On the first run of a settings folder it writes the fork's first-run default: the Creative Agent plugin
 *      (kritamcp) is enabled in <home>/Library/Preferences/<SETTINGS_FOLDER>/kritarc, [python] group, key
 *      enable_kritamcp. A marker file beside kritarc records that this was done, so it never happens again and never
 *      overrides the artist: switching the plugin off in Settings stays off. An existing kritarc is merged into, not
 *      replaced, and a key already present (in any spelling Krita's config files allow) is left alone.
 *      The marker is written only after the file is complete on disk and in place. Any problem (unreadable file, a
 *      folder named kritarc, a read-only file or folder, no memory) means: change nothing, write no marker.
 *   2. It points the libraries that would otherwise look outside the app at the app: PYTHONNOUSERSITE=1 (no packages
 *      from the user's own Python folders) and MLT's repository, data, profiles and presets (Krita sets these only
 *      for AppImage and Android).
 *   3. It execs Contents/MacOS/krita-app, the real Krita executable, with the same arguments.
 *
 * This is a stop-gap that needs no change to Krita: a build whose shipped defaults (krita/data/kritarc, compiled in
 * as :/kconfig/<folder>/kritarc) already enable the plugin makes step 1 unnecessary. See AGENT-FORK.md, "Packaging".
 *
 * Built with -DSETTINGS_FOLDER='"KritaAgent"' (the build's KRITA_APP_SETTINGS_FOLDER). Tests build it with
 * -DKRITA_AGENT_TEST_HOOK, which adds --agent-first-run-only (do step 1 and exit) and --agent-print-env (print step 2's
 * variables and exit); the packaged launcher has neither.
 */
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <pwd.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef SETTINGS_FOLDER
#error "build with -DSETTINGS_FOLDER='\"KritaAgent\"' (the build's KRITA_APP_SETTINGS_FOLDER)"
#endif
#define MARKER_NAME ".agent-first-run-1"
#define PLUGIN_KEY "enable_kritamcp"
#define REAL_EXECUTABLE "krita-app"

enum merge_result { MERGE_CHANGED, MERGE_PRESENT, MERGE_NO_MEMORY };

/* snprintf of "<a><separator><b>" that reports truncation */
static int join(char *buffer, size_t size, const char *a, const char *separator, const char *b)
{
    int n = snprintf(buffer, size, "%s%s%s", a, separator, b);
    return n > 0 && (size_t)n < size ? 0 : -1;
}

static int make_dirs(const char *path)
{
    char buffer[PATH_MAX];
    size_t length = strlen(path);
    if (length == 0 || length >= sizeof buffer) {
        return -1;
    }
    memcpy(buffer, path, length + 1);
    for (size_t i = 1; i < length; ++i) {
        if (buffer[i] == '/') {
            buffer[i] = '\0';
            if (mkdir(buffer, 0755) != 0 && errno != EEXIST) {
                return -1;
            }
            buffer[i] = '/';
        }
    }
    return (mkdir(buffer, 0755) != 0 && errno != EEXIST) ? -1 : 0;
}

/* Read a whole regular file. Returns 0 and a malloc'd NUL-terminated buffer, or -1 with errno set. */
static int read_file(const char *path, char **data, size_t *size)
{
    int fd = open(path, O_RDONLY);
    if (fd < 0) {
        return -1;
    }
    struct stat info;
    if (fstat(fd, &info) != 0 || !S_ISREG(info.st_mode)) {
        close(fd);
        errno = EINVAL;
        return -1;
    }
    size_t capacity = (size_t)info.st_size + 1;
    char *buffer = malloc(capacity);
    if (!buffer) {
        close(fd);
        errno = ENOMEM;
        return -1;
    }
    size_t used = 0;
    while (used < capacity - 1) {
        ssize_t got = read(fd, buffer + used, capacity - 1 - used);
        if (got < 0) {
            int saved = errno;
            free(buffer);
            close(fd);
            errno = saved;
            return -1;
        }
        if (got == 0) {
            break;
        }
        used += (size_t)got;
    }
    close(fd);
    buffer[used] = '\0';
    *data = buffer;
    *size = used;
    return 0;
}

/* Is `line` (`length` bytes, not NUL terminated) the group header "[python]" (a trailing CR or spaces allowed)? */
static int is_python_header(const char *line, size_t length)
{
    while (length > 0 && (line[length - 1] == '\r' || line[length - 1] == ' ')) {
        --length;
    }
    return length == 8 && memcmp(line, "[python]", 8) == 0;
}

/* Does `line` set enable_kritamcp, as "key=", "key =" or "key[$i]=" (KConfig's locale and immutable suffixes)? */
static int sets_plugin_key(const char *line, size_t length)
{
    size_t key = strlen(PLUGIN_KEY);
    if (length < key || memcmp(line, PLUGIN_KEY, key) != 0) {
        return 0;
    }
    const char *at = line + key, *end = line + length;
    if (at < end && *at == '[') {
        while (at < end && *at != ']') {
            ++at;
        }
        if (at < end) {
            ++at;
        }
    }
    while (at < end && (*at == ' ' || *at == '\t')) {
        ++at;
    }
    return at < end && *at == '=';
}

/*
 * Merge "enable_kritamcp=true" into the ini text `old` (`old_size` bytes). A UTF-8 byte order mark and CRLF line ends are
 * kept as they are; the new line uses the file's line end.
 */
static enum merge_result merge_plugin_key(const char *old, size_t old_size, char **result, size_t *result_size)
{
    const char *end = old + old_size;
    const char *line = old;
    const char *insert_at = NULL; /* just after the [python] header line */
    int in_python = 0, crlf = 0;

    if (old_size >= 3 && memcmp(old, "\xEF\xBB\xBF", 3) == 0) {
        line = old + 3;
    }
    while (line < end) {
        const char *next = memchr(line, '\n', (size_t)(end - line));
        size_t length = next ? (size_t)(next - line) : (size_t)(end - line);
        const char *after = next ? next + 1 : end;
        if (length > 0 && line[0] == '[') {
            in_python = is_python_header(line, length);
            if (in_python) {
                insert_at = after;
                crlf = line[length - 1] == '\r';
            }
        } else if (in_python && sets_plugin_key(line, length)) {
            return MERGE_PRESENT;
        }
        line = after;
    }

    const char *eol = crlf ? "\r\n" : "\n";
    size_t eol_length = strlen(eol);
    char key_line[64];
    int key_length = snprintf(key_line, sizeof key_line, "%s=true%s", PLUGIN_KEY, eol);
    if (key_length <= 0 || (size_t)key_length >= sizeof key_line) {
        return MERGE_NO_MEMORY;
    }
    char *out = malloc(old_size + (size_t)key_length + 32);
    if (!out) {
        return MERGE_NO_MEMORY;
    }
    size_t at = 0;
    if (insert_at) {
        size_t head = (size_t)(insert_at - old);
        memcpy(out, old, head);
        at = head;
        if (insert_at == end && old_size > 0 && old[old_size - 1] != '\n') {   /* header is the last line, no line end */
            memcpy(out + at, eol, eol_length);
            at += eol_length;
        }
        memcpy(out + at, key_line, (size_t)key_length);
        at += (size_t)key_length;
        memcpy(out + at, insert_at, old_size - head);
        at += old_size - head;
    } else {
        memcpy(out, old, old_size);
        at = old_size;
        if (at > 0 && out[at - 1] != '\n') {
            memcpy(out + at, eol, eol_length);
            at += eol_length;
        }
        if (at > 0) {
            memcpy(out + at, eol, eol_length);
            at += eol_length;
        }
        memcpy(out + at, "[python]", 8);
        at += 8;
        memcpy(out + at, eol, eol_length);
        at += eol_length;
        memcpy(out + at, key_line, (size_t)key_length);
        at += (size_t)key_length;
    }
    *result = out;
    *result_size = at;
    return MERGE_CHANGED;
}

static void write_marker(const char *marker)
{
    int fd = open(marker, O_WRONLY | O_CREAT, 0644);
    if (fd >= 0) {
        close(fd);
    }
}

static const char *home_folder(void)
{
    /* The home Qt will use: Foundation honours CFFIXED_USER_HOME, else the account's home folder. It ignores $HOME. */
    const char *home = getenv("CFFIXED_USER_HOME");
    if (!home || !*home) {
        struct passwd *entry = getpwuid(getuid());
        home = entry ? entry->pw_dir : NULL;
    }
    if (!home || !*home) {
        home = getenv("HOME");
    }
    return (home && *home) ? home : NULL;
}

static void first_run_defaults(void)
{
    const char *home = home_folder();
    if (!home) {
        return;
    }
    char folder[PATH_MAX], marker[PATH_MAX], kritarc[PATH_MAX], target[PATH_MAX], temporary[PATH_MAX], preferences[PATH_MAX];
    if (join(preferences, sizeof preferences, home, "/Library/Preferences/", SETTINGS_FOLDER) != 0
        || join(folder, sizeof folder, preferences, "", "") != 0
        || join(marker, sizeof marker, folder, "/", MARKER_NAME) != 0
        || join(kritarc, sizeof kritarc, folder, "/", "kritarc") != 0) {
        return;
    }
    struct stat info;
    if (lstat(marker, &info) == 0) {
        return;
    }
    if (make_dirs(folder) != 0) {
        return;
    }

    /* Which file do we change? A symlinked kritarc is followed (the artist keeps it elsewhere on purpose). */
    char *old = NULL;
    size_t old_size = 0;
    mode_t mode = 0600;                                   /* Krita's own kritarc is rw------- */
    strcpy(target, kritarc);
    if (lstat(kritarc, &info) != 0) {
        if (errno != ENOENT) {
            return;                                       /* cannot tell: do nothing */
        }
    } else {
        if (S_ISLNK(info.st_mode)) {
            if (!realpath(kritarc, target) || stat(target, &info) != 0) {
                return;                                   /* a dangling link: not ours to create */
            }
        }
        if (!S_ISREG(info.st_mode) || access(target, W_OK) != 0) {
            return;                                       /* a folder, a device, or a file we may not change */
        }
        mode = info.st_mode & 07777;
        if (read_file(target, &old, &old_size) != 0) {
            return;                                       /* unreadable: ENOENT is the only error that means "no file" */
        }
    }

    char *merged = NULL;
    size_t merged_size = 0;
    enum merge_result result = merge_plugin_key(old ? old : "", old_size, &merged, &merged_size);
    free(old);
    if (result == MERGE_NO_MEMORY) {
        return;
    }
    if (result == MERGE_CHANGED) {
        char *slash = strrchr(target, '/');
        char name[64];
        snprintf(name, sizeof name, "/.kritarc.agent-first-run.%d", (int)getpid());
        if (!slash) {
            free(merged);
            return;
        }
        *slash = '\0';
        int built = join(temporary, sizeof temporary, target, "", name);
        *slash = '/';
        if (built != 0) {
            free(merged);
            return;
        }
        int fd = open(temporary, O_WRONLY | O_CREAT | O_EXCL, mode);
        if (fd < 0) {
            free(merged);
            return;                                       /* read-only folder, or none: no marker */
        }
        size_t written = 0;
        int ok = 1;
        while (written < merged_size) {
            ssize_t put = write(fd, merged + written, merged_size - written);
            if (put <= 0) {
                ok = 0;
                break;
            }
            written += (size_t)put;
        }
        ok = ok && fchmod(fd, mode) == 0 && fsync(fd) == 0;
        ok = (close(fd) == 0) && ok;
        free(merged);
        if (!ok || rename(temporary, target) != 0) {
            unlink(temporary);
            return;
        }
    } else {
        free(merged);
    }
    write_marker(marker);                                 /* only now: the file is complete and in place */
}

/* The bundle's Contents folder and this executable's folder, from this executable's real path. */
static int locate(char *contents, size_t size, char *directory, size_t directory_size)
{
    char self[PATH_MAX], resolved[PATH_MAX];
    uint32_t length = sizeof self;
    if (_NSGetExecutablePath(self, &length) != 0 || !realpath(self, resolved)) {
        return -1;
    }
    char *slash = strrchr(resolved, '/');
    if (!slash) {
        return -1;
    }
    *slash = '\0';
    if (join(directory, directory_size, resolved, "", "") != 0) {
        return -1;
    }
    char *up = strrchr(resolved, '/');
    if (!up) {
        return -1;
    }
    *up = '\0';
    return join(contents, size, resolved, "", "");
}

static int set_bundle_environment(const char *contents, int print_only)
{
    char value[PATH_MAX];
    const char *names[] = {"MLT_REPOSITORY", "MLT_DATA", "MLT_PROFILES_PATH", "MLT_PRESETS_PATH"};
    const char *suffixes[] = {"/PlugIns/mlt", "/Resources/mlt", "/Resources/mlt/profiles", "/Resources/mlt/presets"};
    if (print_only) {
        printf("PYTHONNOUSERSITE=1\n");
    } else {
        setenv("PYTHONNOUSERSITE", "1", 1);
    }
    for (int i = 0; i < 4; ++i) {
        if (join(value, sizeof value, contents, "", suffixes[i]) != 0) {
            return -1;
        }
        if (print_only) {
            printf("%s=%s\n", names[i], value);
        } else {
            setenv(names[i], value, 1);
        }
    }
    return 0;
}

int main(int argc, char **argv)
{
    char contents[PATH_MAX], directory[PATH_MAX], real[PATH_MAX];
    (void)argc;
#ifdef KRITA_AGENT_TEST_HOOK
    if (argc > 1 && strcmp(argv[1], "--agent-first-run-only") == 0) {
        first_run_defaults();
        return 0;
    }
    if (argc > 1 && strcmp(argv[1], "--agent-print-env") == 0) {
        return locate(contents, sizeof contents, directory, sizeof directory) == 0 && set_bundle_environment(contents, 1) == 0 ? 0 : 1;
    }
#endif
    first_run_defaults();
    if (locate(contents, sizeof contents, directory, sizeof directory) != 0
        || join(real, sizeof real, directory, "/", REAL_EXECUTABLE) != 0
        || set_bundle_environment(contents, 0) != 0) {
        fprintf(stderr, "Krita Agent: cannot find its own path\n");
        return 1;
    }
    argv[0] = real;
    execv(real, argv);
    fprintf(stderr, "Krita Agent: cannot start %s: %s\n", real, strerror(errno));
    return 1;
}
