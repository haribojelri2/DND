@echo off
java -Xms2g -Xmx4g -Djava.library.path=natives -cp "OcsMapEditor_JKM.jar;OcsMapEditor_lib/*" dndts.ocsmap.gui.OcsMapEditorGUI
pause
