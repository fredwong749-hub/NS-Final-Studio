"""
NS Latex Tools —— Blender 插件（3.6 / 4.x）

安装: Edit > Preferences > Add-ons > Install... 选择本文件并勾选启用
位置: 3D 视图按 N > 侧栏 "NS Latex"

功能:
  1. 一键生成 latex / 漆皮 / 镀铬金属 材质，并赋给选中物体
  2. 选中的曲线批量转成贴身扁绑带（贴合人体法线 + Shrinkwrap + Solidify，可继续编辑）
  3. 人体上选中的面 -> 贴身 latex 布片（胸下、裆部那种整片）
  4. 在 3D 游标处放 O 环 / 方扣，自动贴合人体表面并对齐法线
"""

bl_info = {
    "name": "NS Latex Tools",
    "author": "NS-Final Studio",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > NS Latex",
    "description": "Latex / patent / chrome materials, curve-to-strap, body panels, rings and buckles",
    "category": "Object",
}

import math

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, PointerProperty
from mathutils import Vector
from mathutils.bvhtree import BVHTree


# ------------------------------------------------------------------ 材质

MATERIAL_PRESETS = {
    "LATEX": ("NS_Latex_Black", dict(
        base=(0.015, 0.015, 0.015, 1.0), metallic=0.0, rough=0.11, rough_var=0.03,
        spec=0.65, coat=0.8, coat_rough=0.02)),
    "PATENT": ("NS_Patent_Black", dict(
        base=(0.005, 0.005, 0.005, 1.0), metallic=0.0, rough=0.045, rough_var=0.015,
        spec=0.5, coat=1.0, coat_rough=0.0)),
    "METAL": ("NS_Metal_Chrome", dict(
        base=(0.8, 0.8, 0.82, 1.0), metallic=1.0, rough=0.12, rough_var=0.04,
        spec=0.5, coat=0.0, coat_rough=0.0)),
}

MATERIAL_ITEMS = [
    ("LATEX", "Latex", "黑色亮面 latex"),
    ("PATENT", "漆皮", "高跟鞋用镜面漆皮"),
    ("METAL", "金属", "O 环 / 扣具用镀铬金属"),
]


def _set_input(node, names, value):
    # Principled BSDF 在 3.x 和 4.x 的输入名不同，按顺序找第一个存在的
    for name in names:
        if name in node.inputs:
            node.inputs[name].default_value = value
            return


def build_material(key):
    name, p = MATERIAL_PRESETS[key]
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (100, 0)
    texco = nt.nodes.new("ShaderNodeTexCoord")
    texco.location = (-750, 0)
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.location = (-550, 0)
    noise.inputs["Scale"].default_value = 120.0
    noise.inputs["Detail"].default_value = 2.0
    rmap = nt.nodes.new("ShaderNodeMapRange")
    rmap.location = (-300, 0)
    rmap.inputs["To Min"].default_value = max(p["rough"] - p["rough_var"], 0.0)
    rmap.inputs["To Max"].default_value = p["rough"] + p["rough_var"]

    # 噪声轻微扰动粗糙度，避免塑料感
    nt.links.new(texco.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], rmap.inputs["Value"])
    nt.links.new(rmap.outputs["Result"], bsdf.inputs["Roughness"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    _set_input(bsdf, ["Base Color"], p["base"])
    _set_input(bsdf, ["Metallic"], p["metallic"])
    _set_input(bsdf, ["Specular IOR Level", "Specular"], p["spec"])
    _set_input(bsdf, ["Coat Weight", "Clearcoat"], p["coat"])
    _set_input(bsdf, ["Coat Roughness", "Clearcoat Roughness"], p["coat_rough"])

    # 视口实体模式下的显示颜色
    mat.diffuse_color = p["base"]
    mat.metallic = p["metallic"]
    mat.roughness = p["rough"]
    return mat


def get_material(key):
    name = MATERIAL_PRESETS[key][0]
    return bpy.data.materials.get(name) or build_material(key)


def assign_material(obj, mat):
    if obj.data is None or not hasattr(obj.data, "materials"):
        return
    obj.data.materials.clear()
    obj.data.materials.append(mat)


# ------------------------------------------------------------------ 人体表面查询

class BodySurface:
    """在人体（含修改器后的结果）上找最近点和平滑法线，世界坐标"""

    def __init__(self, context, body):
        dg = context.evaluated_depsgraph_get()
        self.bm = bmesh.new()
        self.bm.from_object(body, dg)
        self.bm.transform(body.matrix_world)
        self.bm.normal_update()
        self.bm.faces.ensure_lookup_table()
        self.bvh = BVHTree.FromBMesh(self.bm)

    def nearest(self, co):
        loc, fnorm, idx, _dist = self.bvh.find_nearest(co)
        if loc is None:
            return co.copy(), Vector((0.0, 0.0, 1.0))
        # 用所在面的顶点法线按距离加权，比面法线平滑，低模上绑带不会一折一折
        n = Vector()
        for v in self.bm.faces[idx].verts:
            n += v.normal / max((v.co - loc).length, 1e-6)
        if n.length < 1e-8:
            n = fnorm
        return loc, n.normalized()

    def free(self):
        self.bm.free()


def _get_body(context):
    body = context.scene.ns_latex_body
    if body is None or body.type != 'MESH':
        return None
    return body


# ------------------------------------------------------------------ 曲线 -> 绑带

def _curve_chains(context, obj):
    """把曲线（求值后）拆成若干条有序点链，返回 [(points, cyclic), ...]，世界坐标"""
    cu = obj.data
    saved = (cu.bevel_depth, cu.extrude, cu.bevel_object)
    cu.bevel_depth, cu.extrude, cu.bevel_object = 0.0, 0.0, None
    context.view_layer.update()

    dg = context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    mw = obj.matrix_world
    co = [mw @ v.co for v in me.vertices]
    adj = {i: [] for i in range(len(co))}
    for e in me.edges:
        a, b = e.vertices
        adj[a].append(b)
        adj[b].append(a)
    ev.to_mesh_clear()
    cu.bevel_depth, cu.extrude, cu.bevel_object = saved

    seen = set()
    chains = []
    # 先从端点出发（开放曲线），剩下的就是闭合曲线
    starts = [i for i in adj if len(adj[i]) == 1] + list(adj)
    for s in starts:
        if s in seen or not adj[s]:
            continue
        chain = [s]
        seen.add(s)
        prev, cur = None, s
        while True:
            nxt = [n for n in adj[cur] if n != prev and n not in seen]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            chain.append(cur)
            seen.add(cur)
        cyclic = len(chain) > 2 and len(adj[s]) == 2 and s in adj[chain[-1]]
        chains.append(([co[i] for i in chain], cyclic))
    return chains


def _resample(pts, step, cyclic):
    if cyclic:
        pts = pts + [pts[0]]
    seg = [(pts[i + 1] - pts[i]).length for i in range(len(pts) - 1)]
    total = sum(seg)
    if total < 1e-6:
        return []
    n = max(3 if cyclic else 2, int(total / step) + 1)
    out = []
    i, acc = 0, 0.0
    for k in range(n):
        d = total * k / n if cyclic else total * k / (n - 1)
        while i < len(seg) - 1 and acc + seg[i] < d:
            acc += seg[i]
            i += 1
        t = (d - acc) / seg[i] if seg[i] > 0 else 0.0
        out.append(pts[i].lerp(pts[i + 1], min(max(t, 0.0), 1.0)))
    return out


def _smooth(vecs, iterations, cyclic):
    vecs = [v.copy() for v in vecs]
    n = len(vecs)
    for _ in range(iterations):
        new = [v.copy() for v in vecs]
        for i in range(n):
            if not cyclic and (i == 0 or i == n - 1):
                continue
            new[i] = (vecs[i - 1] + vecs[i] * 2.0 + vecs[(i + 1) % n]) / 4.0
        vecs = new
    return vecs


def _build_strap_mesh(name, pts, cyclic, surf, width, offset):
    locs, norms = [], []
    for p in pts:
        loc, n = surf.nearest(p)
        locs.append(loc)
        norms.append(n)
    locs = _smooth(locs, 2, cyclic)
    norms = [n.normalized() for n in _smooth(norms, 3, cyclic)]

    count = len(locs)
    half = width / 2.0
    verts = []
    for i in range(count):
        if cyclic:
            a, b = locs[i - 1], locs[(i + 1) % count]
        else:
            a, b = locs[max(i - 1, 0)], locs[min(i + 1, count - 1)]
        t = (b - a).normalized()
        side = t.cross(norms[i])
        if side.length < 1e-6:
            side = t.orthogonal()
        side.normalize()
        p = locs[i] + norms[i] * offset
        verts += [p - side * half, p + side * half]

    # 顶点顺序保证面法线朝外（远离人体），Solidify 往外长厚度
    faces = []
    segs = count if cyclic else count - 1
    for i in range(segs):
        j = (i + 1) % count
        faces.append((2 * i, 2 * i + 1, 2 * j + 1, 2 * j))

    # 沿长度的累计距离，做 UV（横向 0-1，纵向按宽度等比例平铺）
    cum = [0.0]
    for i in range(1, count):
        cum.append(cum[-1] + (locs[i] - locs[i - 1]).length)
    total = cum[-1] + ((locs[0] - locs[-1]).length if cyclic else 0.0)

    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    uv = me.uv_layers.new(name="UVMap")
    for fi, poly in enumerate(me.polygons):
        poly.use_smooth = True
        for li in poly.loop_indices:
            vi = me.loops[li].vertex_index
            row = vi // 2
            length = total if (cyclic and fi == segs - 1 and row == 0) else cum[row]
            uv.data[li].uv = (float(vi % 2), length / width)
    me.update()
    return me


def _add_fit_modifiers(obj, body, offset, thickness):
    sw = obj.modifiers.new("Shrinkwrap", 'SHRINKWRAP')
    sw.target = body
    sw.wrap_method = 'NEAREST_SURFACEPOINT'
    sw.wrap_mode = 'OUTSIDE_SURFACE'
    sw.offset = offset
    sol = obj.modifiers.new("Solidify", 'SOLIDIFY')
    sol.thickness = thickness
    sol.offset = 1.0
    sol.use_even_offset = True


def _straps_collection(context):
    col = bpy.data.collections.get("NS_Straps")
    if col is None:
        col = bpy.data.collections.new("NS_Straps")
        context.scene.collection.children.link(col)
    return col


def _link_to_body(obj, body):
    obj.parent = body
    obj.matrix_parent_inverse = body.matrix_world.inverted()


class NS_OT_material(bpy.types.Operator):
    bl_idname = "ns_latex.material"
    bl_label = "生成材质"
    bl_description = "生成/重建材质节点，并赋给选中物体"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(items=MATERIAL_ITEMS, name="材质")

    def execute(self, context):
        mat = build_material(self.preset)
        n = 0
        for obj in context.selected_objects:
            if obj.type in {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT'}:
                assign_material(obj, mat)
                n += 1
        self.report({'INFO'}, f"{mat.name} 已生成，赋给 {n} 个物体")
        return {'FINISHED'}


class NS_OT_curves_to_straps(bpy.types.Operator):
    bl_idname = "ns_latex.curves_to_straps"
    bl_label = "曲线 → 绑带"
    bl_description = "把选中的曲线转成贴合人体的扁绑带"
    bl_options = {'REGISTER', 'UNDO'}

    width: FloatProperty(name="宽度", default=0.015, min=0.001, max=0.2, unit='LENGTH', precision=4)
    thickness: FloatProperty(name="厚度", default=0.0015, min=0.0001, max=0.02, unit='LENGTH', precision=4)
    offset: FloatProperty(name="离皮肤", default=0.0005, min=0.0, max=0.02, unit='LENGTH', precision=4)
    step: FloatProperty(name="采样间距", default=0.004, min=0.0005, max=0.05, unit='LENGTH', precision=4,
                        description="越小越贴合，面数越多")
    material: EnumProperty(items=MATERIAL_ITEMS, name="材质", default="LATEX")
    keep_curves: BoolProperty(name="保留曲线（隐藏）", default=True)

    def execute(self, context):
        body = _get_body(context)
        if body is None:
            self.report({'ERROR'}, "先在面板里指定人体对象")
            return {'CANCELLED'}
        curves = [o for o in context.selected_objects if o.type == 'CURVE']
        if not curves:
            self.report({'ERROR'}, "没有选中曲线")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        surf = BodySurface(context, body)
        col = _straps_collection(context)
        mat = get_material(self.material)
        made = []
        try:
            for cobj in curves:
                for k, (pts, cyclic) in enumerate(_curve_chains(context, cobj)):
                    pts = _resample(pts, self.step, cyclic)
                    if len(pts) < 2:
                        continue
                    name = f"{cobj.name}_strap" + (f".{k}" if k else "")
                    me = _build_strap_mesh(name, pts, cyclic, surf, self.width, self.offset)
                    obj = bpy.data.objects.new(name, me)
                    col.objects.link(obj)
                    _link_to_body(obj, body)
                    _add_fit_modifiers(obj, body, self.offset, self.thickness)
                    assign_material(obj, mat)
                    made.append(obj)
        finally:
            surf.free()

        for cobj in curves:
            if self.keep_curves:
                cobj.hide_set(True)
            else:
                bpy.data.objects.remove(cobj, do_unlink=True)
        for o in context.selected_objects:
            o.select_set(False)
        for o in made:
            o.select_set(True)
        if made:
            context.view_layer.objects.active = made[-1]
        self.report({'INFO'}, f"生成 {len(made)} 条绑带")
        return {'FINISHED'}


class NS_OT_faces_to_panel(bpy.types.Operator):
    bl_idname = "ns_latex.faces_to_panel"
    bl_label = "选中面 → latex 布片"
    bl_description = "在人体编辑模式下选中一片面，复制成贴身 latex 布片"
    bl_options = {'REGISTER', 'UNDO'}

    thickness: FloatProperty(name="厚度", default=0.0008, min=0.0001, max=0.02, unit='LENGTH', precision=4)
    offset: FloatProperty(name="离皮肤", default=0.0004, min=0.0, max=0.02, unit='LENGTH', precision=4)
    material: EnumProperty(items=MATERIAL_ITEMS, name="材质", default="LATEX")

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        src = context.edit_object
        bm = bmesh.from_edit_mesh(src.data)
        faces = [f for f in bm.faces if f.select]
        if not faces:
            self.report({'ERROR'}, "没有选中面")
            return {'CANCELLED'}
        mw = src.matrix_world
        vmap, verts, polys = {}, [], []
        for f in faces:
            for v in f.verts:
                if v not in vmap:
                    vmap[v] = len(verts)
                    verts.append(mw @ v.co)
            polys.append([vmap[v] for v in f.verts])
        bpy.ops.object.mode_set(mode='OBJECT')

        me = bpy.data.meshes.new(f"{src.name}_panel")
        me.from_pydata(verts, [], polys)
        for p in me.polygons:
            p.use_smooth = True
        me.update()
        obj = bpy.data.objects.new(me.name, me)
        _straps_collection(context).objects.link(obj)
        _link_to_body(obj, src)
        _add_fit_modifiers(obj, src, self.offset, self.thickness)
        assign_material(obj, get_material(self.material))

        if context.scene.ns_latex_body is None:
            context.scene.ns_latex_body = src
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}


# ------------------------------------------------------------------ 五金件

def _place_on_body(context, obj, lift):
    """把物体放到 3D 游标对应的人体表面，Z 轴对齐法线"""
    co = context.scene.cursor.location.copy()
    body = _get_body(context)
    if body is None:
        obj.location = co
        return
    surf = BodySurface(context, body)
    loc, n = surf.nearest(co)
    surf.free()
    obj.location = loc + n * lift
    obj.rotation_euler = n.to_track_quat('Z', 'Y').to_euler()


def _new_object(context, name, data):
    obj = bpy.data.objects.new(name, data)
    _straps_collection(context).objects.link(obj)
    for o in context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj


class NS_OT_add_ring(bpy.types.Operator):
    bl_idname = "ns_latex.add_ring"
    bl_label = "O 环"
    bl_description = "在 3D 游标处的人体表面放一个 O 环"
    bl_options = {'REGISTER', 'UNDO'}

    radius: FloatProperty(name="半径", default=0.009, min=0.001, max=0.1, unit='LENGTH', precision=4)
    wire: FloatProperty(name="线径半径", default=0.0013, min=0.0002, max=0.01, unit='LENGTH', precision=4)

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        me = bpy.data.meshes.new("NS_Ring")
        bm = bmesh.new()
        # 直接用 bmesh 生成圆环，不依赖 primitive 算子的上下文
        segs, rings = 48, 12
        for i in range(segs):
            a = 2 * math.pi * i / segs
            center = Vector((math.cos(a) * self.radius, math.sin(a) * self.radius, 0.0))
            radial = Vector((math.cos(a), math.sin(a), 0.0))
            for j in range(rings):
                b = 2 * math.pi * j / rings
                bm.verts.new(center + radial * math.cos(b) * self.wire
                             + Vector((0, 0, 1)) * math.sin(b) * self.wire)
        bm.verts.ensure_lookup_table()
        for i in range(segs):
            for j in range(rings):
                i2, j2 = (i + 1) % segs, (j + 1) % rings
                bm.faces.new((bm.verts[i * rings + j], bm.verts[i2 * rings + j],
                              bm.verts[i2 * rings + j2], bm.verts[i * rings + j2]))
        for f in bm.faces:
            f.smooth = True
        bm.normal_update()
        bm.to_mesh(me)
        bm.free()

        obj = _new_object(context, "NS_Ring", me)
        assign_material(obj, get_material("METAL"))
        _place_on_body(context, obj, self.wire)
        body = _get_body(context)
        if body:
            _link_to_body(obj, body)
        return {'FINISHED'}


class NS_OT_add_buckle(bpy.types.Operator):
    bl_idname = "ns_latex.add_buckle"
    bl_label = "方扣"
    bl_description = "在 3D 游标处的人体表面放一个带扣针的方扣，绑带方向沿局部 X 轴"
    bl_options = {'REGISTER', 'UNDO'}

    width: FloatProperty(name="长（沿绑带）", default=0.02, min=0.002, max=0.1, unit='LENGTH', precision=4)
    height: FloatProperty(name="宽（跨绑带）", default=0.019, min=0.002, max=0.1, unit='LENGTH', precision=4)
    wire: FloatProperty(name="线径半径", default=0.0011, min=0.0002, max=0.01, unit='LENGTH', precision=4)

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        w, h = self.width / 2, self.height / 2
        r = min(w, h) * 0.35
        cu = bpy.data.curves.new("NS_Buckle", 'CURVE')
        cu.dimensions = '3D'
        cu.bevel_depth = self.wire
        cu.bevel_resolution = 3
        cu.use_fill_caps = True

        def poly(points, cyclic):
            sp = cu.splines.new('POLY')
            sp.points.add(len(points) - 1)
            for p, (x, y, z) in zip(sp.points, points):
                p.co = (x, y, z, 1.0)
            sp.use_cyclic_u = cyclic

        # 倒角矩形外框
        poly([(-w + r, -h, 0), (w - r, -h, 0), (w, -h + r, 0), (w, h - r, 0),
              (w - r, h, 0), (-w + r, h, 0), (-w, h - r, 0), (-w, -h + r, 0)], True)
        # 中梁
        poly([(0, -h, 0), (0, h, 0)], False)
        # 扣针，略微抬起压在绑带上
        poly([(0, 0, self.wire), (w * 0.95, 0, self.wire * 2.5)], False)

        obj = _new_object(context, "NS_Buckle", cu)
        assign_material(obj, get_material("METAL"))
        _place_on_body(context, obj, self.wire * 2)
        body = _get_body(context)
        if body:
            _link_to_body(obj, body)
        return {'FINISHED'}


# ------------------------------------------------------------------ 面板

class NS_PT_latex(bpy.types.Panel):
    bl_label = "NS Latex"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "NS Latex"

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "ns_latex_body", text="人体")

        box = layout.box()
        box.label(text="材质（赋给选中物体）")
        row = box.row(align=True)
        for key, label, _ in MATERIAL_ITEMS:
            row.operator(NS_OT_material.bl_idname, text=label).preset = key

        box = layout.box()
        box.label(text="绑带 / 布片")
        box.operator(NS_OT_curves_to_straps.bl_idname, icon='CURVE_BEZCURVE')
        box.operator(NS_OT_faces_to_panel.bl_idname, icon='FACESEL')

        box = layout.box()
        box.label(text="五金（放在 3D 游标处）")
        row = box.row(align=True)
        row.operator(NS_OT_add_ring.bl_idname, icon='MESH_TORUS')
        row.operator(NS_OT_add_buckle.bl_idname, icon='MESH_PLANE')


classes = (
    NS_OT_material,
    NS_OT_curves_to_straps,
    NS_OT_faces_to_panel,
    NS_OT_add_ring,
    NS_OT_add_buckle,
    NS_PT_latex,
)


def _body_poll(_self, obj):
    return obj.type == 'MESH'


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.ns_latex_body = PointerProperty(type=bpy.types.Object, poll=_body_poll, name="人体")


def unregister():
    del bpy.types.Scene.ns_latex_body
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
