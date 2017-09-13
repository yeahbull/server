import os
import re
import shutil
from zlib import crc32
from collections import defaultdict

from parser import SourceBuilder, TLParser
from parser.tl_object import TLObject, TLArg
AUTO_GEN_NOTICE = \
    '// File generated by TLObjects\' generator. All changes will be ERASED'


class TLGenerator:
    def __init__(self, output_dir):
        self.output_dir = output_dir

    def _get_file(self, *paths):
        return os.path.join(self.output_dir, *paths)

    def _rm_if_exists(self, filename):
        file = self._get_file(filename)
        if os.path.exists(file):
            if os.path.isdir(file):
                shutil.rmtree(file)
            else:
                os.remove(file)

    def clean_tlobjects(self):
        for name in ('functions.cpp', 'types.cpp'):
            self._rm_if_exists(name)

    def generate_tlobjects(self, scheme_files):
        os.makedirs(self.output_dir, exist_ok=True)

        tlobjects = tuple(TLParser.parse_files(scheme_files, ignore_core=True))

        namespace_functions = defaultdict(list)
        namespace_types = defaultdict(list)
        function_abstracts = set()
        object_abstracts = set()

        for tlobject in tlobjects:
            tlobject.result = TLArg.get_sanitized_result(tlobject.result)
            
            if tlobject.is_function:
                namespace_functions[tlobject.namespace].append(tlobject)
                function_abstracts.add(tlobject.result)
            else:
                namespace_types[tlobject.namespace].append(tlobject)
                object_abstracts.add(tlobject.result)

        self._generate_source(self._get_file('functions.cpp'), namespace_functions, function_abstracts)
        self._generate_source(self._get_file('types.cpp'), namespace_types, object_abstracts)

    @staticmethod
    def _generate_source(file, namespace_tlobjects, abstracts):
        # namespace_tlobjects: {'namespace', [TLObject]}
        with open(file, 'w', encoding='utf-8') as f, SourceBuilder(f) as builder:
            builder.writeln(AUTO_GEN_NOTICE)
            builder.writeln('#include <optional>')
            builder.writeln('#include <string>')
            builder.writeln('#include <vector>')
            builder.writeln('#include <stdint.h>')
            builder.writeln()
            builder.writeln('namespace TL {')

            builder.writeln('namespace Type {')
            for a in sorted(abstracts):
                builder.writeln('class {} : public Serializable {{ }}'.format(a))
            builder.end_block()

            lastlayer = 0
            for ns, tlobjects in namespace_tlobjects.items():

                # Generate the class for every TLObject
                for t in sorted(tlobjects, key=lambda x: x.name):
                    if lastlayer != t.layer:
                        builder.writeln('namespace {} {{'.format(t.layer))
                        lastlayer = t.layer
                    if ns:
                        builder.writeln('namespace {} {{'.format(ns))
                        ns = None

                    TLGenerator._write_source_code(t, builder)

                if ns:
                    builder.end_block()
            builder.end_block()


    @staticmethod
    def _write_source_code(tlobject, builder):
        class_name = TLObject.get_class_name(tlobject)
        builder.writeln('class {} : public TL::Type::{} {{'.format(class_name, tlobject.result))
        builder.current_indent -= 1
        builder.writeln('public:')
        builder.current_indent += 1

        builder.writeln('static const uint32_t CONSTRUCTOR = {};'.format(
            hex(tlobject.id)
        ))
        builder.writeln()

        # Flag arguments must go last
        args = [
            a for a in tlobject.sorted_args()
            if not a.flag_indicator and not a.generic_definition
        ]

        for arg in args:
            builder.writeln('{};'.format(arg.get_type_name('TL::Type::')))

        # Write the constructor
        params = [arg.get_type_name('TL::Type::') if not arg.is_flag
                  else '{} = {{}}'.format(arg.get_type_name('TL::Type::')) for arg in args]

        builder.writeln()
        builder.writeln(
            '{}({}) {{'.format(class_name, ', '.join(params))
        )

        for arg in args:
            builder.writeln('this->{} = {};'.format(arg.name, arg.name))

        builder.end_block()

        builder.writeln('void write(Stream &stream) override {')
        builder.writeln('stream << {}::CONSTRUCTOR;'.format(class_name))
        for arg in args:
            if arg.is_vector:
                if arg.use_vector_id:
                    builder.writeln('stream << 0x1cb5c415;')
                builder.writeln('stream << static_cast<uint32_t>({}.size());'.format(arg.name))
                builder.writeln('for (auto const& _x: {}) {{'.format(arg.name))
                builder.writeln('stream << _x;')
                builder.end_block()
            else:
                builder.writeln('stream << {};'.format(arg.name))
        builder.end_block()

        builder.writeln('void read(Stream &stream) override {')
        if any(a for a in args if a.is_vector):
            builder.writeln('uint32_t _len, _i;')
        for arg in args:
            if arg.is_vector:
                if arg.use_vector_id:
                    builder.writeln('stream >> _i;')
                builder.writeln('stream >> _len;')
                builder.writeln('for (_i = 0; i != _len; ++_i) {')
                # TODO Actually read the TLObject
                builder.writeln('/* TODO Actually read the TLObject */')
                builder.end_block()
            else:
                builder.writeln('stream >> {};'.format(arg.name))
        builder.end_block()
        builder.end_block()

if __name__ == '__main__':
    generator = TLGenerator('../Thallium/tl')
    print('Detected previous TLObjects. Cleaning...')
    generator.clean_tlobjects()

    print('Generating TLObjects...')
    generator.generate_tlobjects({1: "schemes/TL_mtproto_v1.json", 71: "schemes/TL_telegram_v71.tl"})

    print('Done.')
