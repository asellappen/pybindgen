## -*- python -*-
## (C) 2007,2008 Gustavo J. A. M. Carneiro

import Options
import Build
import Scripting

import Configure
Configure.autoconfig = True
import Logs

#from Params import fatal

import os
import pproc as subprocess
import shutil
import sys
import Configure
import tarfile
import re
import types

import Task
Task.file_deps = Task.extract_deps


APPNAME='pybindgen'
srcdir = '.'
blddir = 'build'



## Add the pybindgen dir to PYTHONPATH, so that the examples and tests are properly built before pybindgen is installed.
os.environ['PYTHONPATH'] = os.getcwd()


def _get_version_from_bzr_lib(path):
    import bzrlib.tag, bzrlib.branch
    fullpath = os.path.abspath(path)
    if sys.platform == 'win32':
        fullpath = fullpath.replace('\\', '/')
        fullpath = '/' + fullpath
    branch = bzrlib.branch.Branch.open('file://' + fullpath)
    tags = bzrlib.tag.BasicTags(branch)
    #print "Getting version information from bzr branch..."
    history = branch.revision_history()
    history.reverse()
    ## find closest tag
    version = None
    extra_version = []
    for revid in history:
        #print revid
        for tag_name, tag_revid in tags.get_tag_dict().iteritems():
            if tag_revid == revid:
                #print "%s matches tag %s" % (revid, tag_name)
                version = [int(s) for s in tag_name.split('.')]
                ## if the current revision does not match the last
                ## tag, we append current revno to the version
                if tag_revid != branch.last_revision():
                    extra_version = [branch.revno()]
                break
        if version:
            break
    assert version is not None
    _version = version + extra_version
    return _version


def _get_version_from_bzr_command(path):
    # get most recent tag first
    most_recent_tag = None
    proc = subprocess.Popen(['bzr', 'log', '--short'], stdout=subprocess.PIPE)
    reg = re.compile('{([0-9]+)\.([0-9]+)\.([0-9]+)}')
    for line in proc.stdout:
        result = reg.search(line)
        if result is not None:
            most_recent_tag = [int(result.group(1)), int(result.group(2)), int(result.group(3))]
            break
    proc.stdout.close()
    proc.wait()
    assert most_recent_tag is not None
    # get most recent revno
    most_recent_revno = None
    proc = subprocess.Popen(['bzr', 'revno'], stdout=subprocess.PIPE)
    most_recent_revno = int(proc.stdout.read().strip())
    proc.wait()
    version = most_recent_tag + [most_recent_revno]
    return version
    

_version = None
def get_version_from_bzr(path):
    global _version
    if _version is not None:
        return _version
    try:
        import bzrlib.tag, bzrlib.branch
    except ImportError:
        return _get_version_from_bzr_command(path)
    else:
        return _get_version_from_bzr_lib(path)

    
def get_version(path=None):
    if path is None:
        path = srcdir
    try:
        return '.'.join([str(x) for x in get_version_from_bzr(path)])
    except ImportError:
        return 'unknown'

def generate_version_py(force=False, path=None):
    """generates pybindgen/version.py, unless it already exists"""

    filename = os.path.join('pybindgen', 'version.py')
    if not force and os.path.exists(filename):
        return

    if path is None:
        path = srcdir
    version = get_version_from_bzr(path)
    dest = open(filename, 'w')
    if isinstance(version, list):
        dest.write('__version__ = %r\n' % (version,))
        dest.write('"""[major, minor, micro, revno], '
                   'revno omitted in official releases"""\n')
    else:
        dest.write('__version__ = "%s"\n' % (version,))
    dest.close()
    

def dist_hook():
    blddir = '../build'
    srcdir = '..'
    version = get_version(srcdir)
    subprocess.Popen([os.path.join(srcdir, "generate-ChangeLog")],  shell=True).wait()
    try:
        os.chmod(os.path.join(srcdir, "ChangeLog"), 0644)
    except OSError:
        pass
    shutil.copy(os.path.join(srcdir, "ChangeLog"), '.')

    ## Write a pybindgen/version.py file containing the project version
    generate_version_py(force=True, path=srcdir)

    ## Copy it to the source dir
    shutil.copy(os.path.join('pybindgen', 'version.py'), os.path.join(srcdir, "pybindgen"))

    ## Copy WAF to the distdir
    #assert os.path.basename(sys.argv[0]) == 'waf'
    shutil.copy(os.path.join(srcdir, sys.argv[0]), '.')

    ## Package the api docs in a separate tarball
    apidocs = 'apidocs'
    if not os.path.isdir('apidocs'):
        Logs.warn("Not creating apidocs archive: the `apidocs' directory does not exist")
    else:
        tar = tarfile.open(os.path.join("..", "pybindgen-%s-apidocs.tar.bz2" % version), 'w:bz2')
        tar.add('apidocs', "pybindgen-%s-apidocs" % version)
        tar.close()
        shutil.rmtree('apidocs', True)

    ## This is a directory I usually keep in my tree -- gjc
    shutil.rmtree('pybindgen-google-code', True)

    shutil.rmtree('.shelf', True)

    try:
        os.unlink('waf-light')
    except OSError:
        pass


def set_options(opt):
    opt.tool_options('python')
    opt.tool_options('compiler_cc')
    opt.tool_options('compiler_cxx')
    opt.tool_options('cflags')

    optgrp = opt.add_option_group("PyBindGen Options")

    if os.path.isdir(".bzr"):
        optgrp.add_option('--generate-version',
                          help=('Generate a new pybindgen/version.py file from version control'
                                ' introspection.  Only works from a bzr checkout tree, and is'
                                ' meant to be used by pybindgen developers only.'),
                          action="store_true", default=False,
                          dest='generate_version')

    optgrp.add_option('--examples',
                      help=('Compile the example programs.'),
                      action="store_true", default=False,
                      dest='examples')

    optgrp.add_option('--disable-pygccxml',
                      help=('Disable pygccxml for unit tests / examples.'),
                      action="store_true", default=False,
                      dest='disable_pygccxml')

def configure(conf):

    def _check_compilation_flag(conf, flag):
        """
        Checks if the C++ compiler accepts a certain compilation flag or flags
        flag: can be a string or a list of strings
        """

        env = conf.env.copy()
        env.append_value('CXXFLAGS', flag)
        try:
            retval = conf.run_c_code(code='#include <stdio.h>\nint main() { return 0; }\n',
                                     env=env, compile_filename='test.cc',
                                     compile_mode='cxx',type='cprogram', execute=False)
        except Configure.ConfigurationError:
            ok = False
        else:
            ok = (retval == 0)
        conf.check_message_custom(flag, 'support', (ok and 'yes' or 'no'))
        return ok

    conf.check_compilation_flag = types.MethodType(_check_compilation_flag, conf)

    ## Write a pybindgen/version.py file containing the project version
    generate_version_py()

    conf.check_tool('command')
    conf.check_tool('python')
    conf.check_python_version((2,3))

    try:
        conf.check_tool('compiler_cc')
        conf.check_tool('compiler_cxx')
    except Configure.ConfigurationError:
        Logs.warn("C/C++ compiler not detected.  Unit tests and examples will not be compiled.")
        conf.env['CXX'] = ''
    else:
        conf.check_tool('cflags')
        conf.check_python_headers()

        if not Options.options.disable_pygccxml:
            gccxml = conf.find_program('gccxml')
            if not gccxml:
                conf.env['ENABLE_PYGCCXML'] = False
            else:
                try:
                    conf.check_python_module('pygccxml')
                except Configure.ConfigurationError:
                    conf.env['ENABLE_PYGCCXML'] = False
                else:
                    conf.env['ENABLE_PYGCCXML'] = True

        # -fvisibility=hidden optimization
        if (conf.env['CXX_NAME'] == 'gcc' and [int(x) for x in conf.env['CC_VERSION']] >= [4,0,0]
            and conf.check_compilation_flag('-fvisibility=hidden')):
            conf.env.append_value('CXXFLAGS_PYEXT', '-fvisibility=hidden')
            conf.env.append_value('CCFLAGS_PYEXT', '-fvisibility=hidden')


def build(bld):
    global g_bld
    g_bld = bld
    if getattr(Options.options, 'generate_version', False):
        generate_version_py(force=True)

    bld.add_subdirs('pybindgen')
    if Options.options.examples:
        bld.add_subdirs('examples')
    if Options.commands['check'] or Options.commands['clean']:
        bld.add_subdirs('tests')

check_context = Build.BuildContext
def check(bld):
    "run the unit tests"
    Scripting.build(bld)
    print "Running pure python unit tests..."
    retval1 = subprocess.Popen([Build.bld.env['PYTHON'], 'tests/test.py']).wait()

    env = g_bld.env

    if env['CXX']:
        print "Running manual module generation unit tests (module foo)..."
        retval2 = subprocess.Popen([env['PYTHON'], 'tests/footest.py', '1']).wait()
    else:
        print "Skipping manual module generation unit tests (no C/C++ compiler)..."
        retval2 = 0

    if env['ENABLE_PYGCCXML']:
        print "Running automatically scanned module generation unit tests (module foo2)..."
        retval3 = subprocess.Popen([env['PYTHON'], 'tests/footest.py', '2']).wait()

        print "Running module generated by automatically generated python script unit tests (module foo3)..."
        retval3b = subprocess.Popen([env['PYTHON'], 'tests/footest.py', '3']).wait()

        print "Running module generated by generated and split python script unit tests  (module foo4)..."
        retval3c = subprocess.Popen([env['PYTHON'], 'tests/footest.py', '4']).wait()

        print "Running semi-automatically scanned c-hello module ('hello')..."
        retval4 = subprocess.Popen([env['PYTHON'], 'tests/c-hello/hellotest.py']).wait()
    else:
        print "Skipping automatically scanned module generation unit tests (pygccxml missing)..."
        print "Skipping module generated by automatically generated python script unit tests (pygccxml missing)..."
        print "Skipping module generated by generated and split python script unit tests  (pygccxml missing)..."
        print "Skipping semi-automatically scanned c-hello module (pygccxml missing)..."
        retval3 = retval3b = retval3c = retval4 = 0

    if retval1 or retval2 or retval3 or retval3b or retval3c or retval4:
        Logs.error("Unit test failures")
        raise SystemExit(2)


def generate_api_docs(ctx):
    "generate API documentation, using epydoc"
    generate_version_py(force=True)
    retval = subprocess.Popen(["epydoc", "-v", "--html", "--graph=all",  "pybindgen",
                               "-o", "apidocs",
                               "--pstat=build/foomodulegen-auto.pstat",
                                   "--pstat=build/foomodulegen.pstat",
                               "--pstat=build/hellomodulegen.pstat",
                               "--no-private",
                               ]).wait()
    if retval:
        Logs.error("epydoc returned with code %i" % retval)
        raise SystemExit(2)

    # Patch the generated CSS file to highlight literal blocks (this is a copy of pre.py-doctest)
    css = open("apidocs/epydoc.css", "at")
    css.write("""
pre.literalblock {  padding: .5em; margin: 1em;
                    background: #e8f0f8; color: #000000;
                    border: 1px solid #708890; }
""")
    css.close()
