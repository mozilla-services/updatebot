#!/bin/bash

mkdir new || exit
cd new || exit
git init >/dev/null 2>/dev/null

make_bundle () {
	HASH=$(git log --format="%H" HEAD | head -n 1)
	git bundle create "test-repo-$HASH.bundle" HEAD master >/dev/null 2>/dev/null
}

make_full_bundle () {
	HASH=$(git log --format="%H" HEAD | head -n 1)
	git bundle create "test-repo-$HASH.bundle" HEAD --all >/dev/null 2>/dev/null
}

make_final_bundle () {
	git bundle create "test-repo.bundle" HEAD --all >/dev/null 2>/dev/null
}

# ----------------------------------------------------------------
echo "this is the project README" > README
git add README

git commit -m "Add README file" -q
make_bundle
# ----------------------------------------------------------------
cat << EOF > main.c
#include <stdio>

int main() {
  printf("Hello World\n");
  return 0;
}
EOF
git add main.c

git commit -m "Add main.c" -q
make_bundle
# ----------------------------------------------------------------
cat << EOF > main.c
#include <stdio>

int main(int argc, char* argv[]) {
  printf("Hello World\n");
  return 0;
}
EOF
git add main.c

git commit -m "main() should ahve arguments" -q
git tag v0.0.1
make_bundle
# ----------------------------------------------------------------
cat << EOF > do_more.c
#include <stdio>
#include <cstring>

void print_strings(char* a, char* b) {
  char c[500];
  memcpy(c, a, strlen(a));
  memcpy(c + strlen(a), b, strlen(b));
  c[strlen(a) - 1 + strlen(b) - 1 + 1] = '\0';
  printf("%s", c);
}
EOF
git add do_more.c

git commit -m "Utility function for printing strings" -q
make_bundle
# ----------------------------------------------------------------
cat << EOF > do_more.c
#include <stdio>
#include <cstring>

void print_strings(char* a, char* b) {
  char c[50000];
  memcpy(c, a, strlen(a));
  memcpy(c + strlen(a), b, strlen(b));
  c[strlen(a) - 1 + strlen(b) - 1 + 1] = '\0';
  printf("%s", c);
}
EOF
git add do_more.c

git commit -m "Fix a potential bufer overflow" -q
git tag v0.0.2
make_bundle
# ----------------------------------------------------------------
git mv do_more.c utilities.c

git commit -m "Rename file" -q
make_bundle
# ----------------------------------------------------------------
cat << EOF > README
this is the project README

NOTICE: We had a security vulnerability, be careful
EOF
git add README

git commit -m "Update readme for CVE-2021-1" -q
git tag v0.0.3
make_bundle
# ----------------------------------------------------------------
git rm utilities.c >/dev/null 2>/dev/null

git commit -m "Maybe just remove this function completely" -q
make_bundle
# ----------------------------------------------------------------
git checkout -b somebranch -q >/dev/null 2>/dev/null
cat << EOF > functionality.c
void dostuff() {

}
EOF
git add functionality.c

git commit -m "Skeleton for some functionality" -q
make_full_bundle
# ----------------------------------------------------------------
cat << EOF > functionality.c
#include <stdlib>

void dostuff() {
  rand();
}
EOF
git add functionality.c

git commit -m "Add functionality" -q
make_full_bundle
# ----------------------------------------------------------------
git checkout master >/dev/null 2>/dev/null
git checkout -b anotherbranch >/dev/null 2>/dev/null

cat << EOF > main.c
#include <stdio>

int main(int argc, char* argv[]) {
  printf("Hello Universe\n");
  return 0;
}
EOF
git add main.c


git commit -m "Change our message" -q
make_full_bundle
# ----------------------------------------------------------------
make_final_bundle

echo ""
echo "Here is the comment for functionality_commitalert.py"
echo ""
git log --all --graph --format="%H - %s%d" | cat

echo ""
echo "Here are the arrays of commits for functionality_commitalert.py"

git checkout somebranch >/dev/null 2>/dev/null
echo "COMMITS_BRANCH1 = ["
git log --format="    \"%H\"," | cat
echo "]"

git checkout anotherbranch >/dev/null 2>/dev/null
echo "COMMITS_BRANCH2 = ["
git log --format="    \"%H\"," | cat
echo "]"

git checkout master >/dev/null 2>/dev/null
echo "COMMITS_MAIN = ["
git log --format="    \"%H\"," | cat
echo "]"