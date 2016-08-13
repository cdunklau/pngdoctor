import os

from setuptools import setup


#here = os.path.abspath(os.path.dirname(__file__))
#with open(os.path.join(here, 'README.txt'), encoding='utf-8') as f:
#    README = f.read()
#with open(os.path.join(here, 'CHANGES.txt'), encoding='utf-8') as f:
#    CHANGES = f.read()

requires = []

# TODO
classifiers = [] 

setup(
    name='pngdoctor',
    version='0.0',
    # TODO
    description='',
    # TODO
    #long_description=README + '\n\n' + CHANGES,
    classifiers=classifiers,
    author='Colin Dunklau',
    author_email='colin.dunklau@gmail.com',
    url='',
    # TODO
    keywords='',
    packages=['pngdoctor', 'pngdoctor.tests'],
    include_package_data=True,
    zip_safe=False,
    install_requires=requires,
    entry_points={'console_scripts': ['pngdoctor = pngdoctor.main:main']},
)
